"""How to search SimDB well: paging, date windows, free text, result columns, caches.

The MCP tools in server.py only check arguments and shape answers; the logic is here. Much of
it works around how SimDB 0.15.x servers (as on simdb.iter.org) answer `GET /simulations`
(simdb/database/database.py in that release):

* Paging and the total count are computed over (simulation x requested key) rows, and the
  count is divided by the number of keys. Asking for extra columns therefore gives pages of
  the wrong size and fractional counts. So searches ask for the filtered keys only and fetch
  the display columns separately.
* Matches come back in no particular order, and upload date cannot be sorted on. So date
  searches fetch the whole window and sort it here.
* Constraints with an empty value are dropped, so `exist` filters are applied here.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from .client import SimDBError, SimDBSession, SimDBTimeout
from .config import Settings
from .keys import flatten_schema, text_key_priority
from .query import CREATION_DATE, Filter, build_params, column_params
from .records import clean_value, metadata_dict

KEY_LIST_TTL = 300.0
KEY_VALUES_TTL = 600.0
VALIDATION_RULES_TTL = 3600.0
PARALLEL_REQUESTS = 8  # per tool call

TEXT_TYPES = {"string", "str"}  # as reported by /metadata on Postgres / SQLite servers
OBJECT_TYPES = {"object"}


class TTLCache:
    """A dict whose entries expire after `ttl` seconds."""

    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        return entry[1] if entry and entry[0] > time.monotonic() else None

    def put(self, key: str, value: Any) -> Any:
        self._entries[key] = (time.monotonic() + self._ttl, value)
        return value


@dataclass
class Page:
    """One page of simulations (raw SimDB rows) and what is known about the total."""

    rows: list[dict]
    count: float
    approximate: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class TextMatches:
    """Result of a free-text search across several keys."""

    matches: dict[str, dict] = field(default_factory=dict)  # uuid -> row with 'matched_keys'
    keys_queried: list[str] = field(default_factory=list)
    keys_with_more: list[str] = field(default_factory=list)  # more hits than the limit
    errors: dict[str, str] = field(default_factory=dict)  # key -> error message


def with_keys(rows: list[dict], keys: list[str]) -> list[dict]:
    """The rows whose metadata has all of `keys` (applies `exist` filters)."""
    if not keys:
        return rows
    return [r for r in rows if all(k in metadata_dict(r.get("metadata")) for k in keys)]


def short_columns(columns: list[str]) -> list[str]:
    """The columns cheap enough to fetch for a whole date window; long text is fetched per page."""
    return [c for c in columns if "description" not in c and "comment" not in c] or ["status"]


def newest_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: str(r.get("datetime") or ""), reverse=True)


class Catalogue:
    """Metadata discovery and search. One instance serves all tool calls of the server."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._key_lists = TTLCache(KEY_LIST_TTL)  # per user
        # /metadata/<key> is catalogue-wide, the same for every user, so one cache serves all.
        self._key_values = TTLCache(KEY_VALUES_TTL)
        self._validation_rules = TTLCache(VALIDATION_RULES_TTL)

    # -- discovering keys and values ---------------------------------------------------

    async def key_values(self, session: SimDBSession, key: str) -> list:
        """Distinct stored values of one key."""
        cached = self._key_values.get(key)
        if cached is None:
            cached = self._key_values.put(key, await session.list_metadata_values(key))
        return cached

    async def all_keys(self, session: SimDBSession, user: str, expand_objects: bool = True) -> list[dict]:
        """Every metadata key as {'name', 'type'}; with `expand_objects`, also the dotted
        sub-keys of object-valued keys (only newer servers store objects; older ones flatten)."""
        keys = self._key_lists.get(user)
        if keys is None:
            keys = self._key_lists.put(user, await session.list_metadata_keys())
        keys = [dict(k) for k in keys]
        if expand_objects:
            objects = [k["name"] for k in keys if str(k.get("type", "")).lower() in OBJECT_TYPES]
            for found in await asyncio.gather(*(self._sub_keys(session, n) for n in objects), return_exceptions=True):
                if isinstance(found, dict):
                    keys.extend({"name": n, "type": t, "nested": True} for n, t in sorted(found.items()))
        return keys

    async def _sub_keys(self, session: SimDBSession, key: str, sample: int = 50) -> dict[str, str]:
        """{dotted sub-key: type} found in the stored values of an object-valued key."""
        found: dict[str, str] = {}

        def walk(prefix: str, obj: dict) -> None:
            for name, value in obj.items():
                sub_key = f"{prefix}.{name}"
                if isinstance(value, dict) and not {"min", "max"} <= value.keys() and "_type" not in value:
                    walk(sub_key, value)
                else:
                    found.setdefault(sub_key, "string" if isinstance(value, str) else type(value).__name__)

        for value in (await self.key_values(session, key))[:sample]:
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    continue
            if isinstance(value, dict):
                walk(key, value)
        return found

    async def text_keys(self, session: SimDBSession, user: str) -> list[str]:
        """'alias' and every text-valued key, most descriptive first."""
        keys = await self.all_keys(session, user)
        text = {k["name"] for k in keys if str(k.get("type", "")).lower() in TEXT_TYPES}
        return ["alias"] + sorted(text, key=text_key_priority)

    async def validation_rules(self, session: SimDBSession) -> dict[str, dict]:
        """The server's validation rule per dotted key, e.g. {'code.name': {'required': True}}."""
        rules = self._validation_rules.get("all")
        if rules is None:
            rules = self._validation_rules.put("all", flatten_schema(await session.validation_schema()))
        return rules

    # -- structured search ---------------------------------------------------------------

    async def search(
        self,
        session: SimDBSession,
        filters: list[Filter],
        columns: list[str],
        limit: int,
        page: int,
        sort_by: str = "",
        sort_asc: bool = False,
    ) -> Page:
        """One page of simulations matching all `filters`, with `columns` in their metadata."""
        params = build_params(filters)  # raises ValueError for filters SimDB cannot express
        filtered = {f.key for f in filters}
        exist_keys = [f.key for f in filters if f.op == "exist"]
        columns = [c for c in columns if c and c not in filtered]

        if CREATION_DATE in filtered:
            result = await self._search_date_window(session, params, filtered, exist_keys, columns, limit, page)
        else:
            result = None
            if filters and columns:
                result = await self._search_all_at_once(
                    session, params, exist_keys, columns, limit, page, sort_by, sort_asc
                )
            if result is None:
                result = await self._search_paged(session, params, exist_keys, limit, page, sort_by, sort_asc)
                await self._add_columns_or_note(session, result, columns)
        return result

    async def _search_date_window(self, session, params, filtered, exist_keys, columns, limit, page) -> Page:
        """Upload-date filter: fetch the whole window, newest first, and page here."""
        # With only creation_date (not a metadata key) the server returns no rows at all,
        # so ask for a short column to anchor the results.
        anchor = [] if filtered - {CREATION_DATE} else short_columns(columns)
        notes: list[str] = []
        rows = with_keys(await self.fetch_window(session, params + column_params(anchor), notes), exist_keys)
        result = Page(rows[(page - 1) * limit : page * limit], len(rows), notes=notes)
        await self._add_columns_or_note(session, result, columns)
        return result

    async def _search_all_at_once(
        self, session, params, exist_keys, columns, limit, page, sort_by, sort_asc
    ) -> Page | None:
        """Every match with its columns in one request, or None when there may be more.

        The server caps the reply at max_limit x (number of keys) rows, and a simulation gives
        at most one row per key, so fewer than max_limit simulations means nothing was cut
        (newer servers simply cap at max_limit simulations)."""
        cap = self.settings.max_limit
        data = await session.list_simulations(params + column_params(columns), cap, 1, sort_by, sort_asc)
        rows = data.get("results", [])
        if len(rows) >= cap:
            return None
        rows = with_keys(rows, exist_keys)
        return Page(rows[(page - 1) * limit : page * limit], len(rows))

    async def _search_paged(self, session, params, exist_keys, limit, page, sort_by, sort_asc) -> Page:
        """Let the server page, asking only for the filtered keys so its count stays right."""
        data = await session.list_simulations(params, limit, page, sort_by, sort_asc)
        rows = with_keys(data.get("results", []), exist_keys)[:limit]
        count = data.get("count", len(rows))
        return Page(rows, count, approximate=bool(exist_keys) or float(count) != round(float(count)))

    async def fetch_window(self, session: SimDBSession, params: list[tuple[str, str]], notes: list[str]) -> list[dict]:
        """Every match in one request (limit 0 means no limit), newest upload first.

        With only upload-date constraints, SimDB 0.15 loads every metadata row of every
        simulation in the window before filtering, which can time out for wide windows. On a
        timeout, retry with an always-true constraint on 'status' so the server loads only that
        key's rows (simulations without a 'status' key are then missed, and a note says so)."""
        try:
            data = await session.list_simulations(params, 0)
        except SimDBTimeout:
            if any(k == "status" for k, _ in params):
                raise
            data = await session.list_simulations(params + [("status", "ne:__no_such_status__")], 0)
            notes.append(
                "The server timed out; retried listing only simulations that have a "
                "'status' key. Narrow the date window for a complete list."
            )
        return newest_first(data.get("results", []))

    async def add_columns(self, session: SimDBSession, rows: list[dict], columns: list[str]) -> int:
        """Merge `columns` into each row's metadata, one small request per simulation.
        Returns how many simulations failed."""
        limiter = asyncio.Semaphore(PARALLEL_REQUESTS)

        async def fill(row: dict) -> bool:
            uuid = clean_value(row.get("uuid"))
            async with limiter:
                try:
                    data = await session.list_simulations([("uuid", f"eq:{uuid}")] + column_params(columns), 1)
                except SimDBError:
                    return False
            metadata = metadata_dict(row.get("metadata"))
            for hit in data.get("results", []):
                if clean_value(hit.get("uuid")) == uuid:
                    metadata.update(metadata_dict(hit.get("metadata")))
            row["metadata"] = metadata
            return True

        return (await asyncio.gather(*(fill(r) for r in rows))).count(False)

    async def _add_columns_or_note(self, session: SimDBSession, page: Page, columns: list[str]) -> None:
        if columns and page.rows and (failed := await self.add_columns(session, page.rows, columns)):
            page.notes.append(f"Columns could not be loaded for {failed} simulation(s).")

    # -- recent uploads -------------------------------------------------------------------

    async def recent(
        self, session: SimDBSession, since: str, until: str | None, columns: list[str], limit: int
    ) -> Page:
        """Simulations uploaded in [since, until), newest first. `count` covers the whole window.
        `since` and `until` are already in SimDB's creation_date format."""
        params = [(CREATION_DATE, f"ge:{since}")] + ([(CREATION_DATE, f"lt:{until}")] if until else [])
        short = short_columns(columns)
        notes: list[str] = []
        rows = await self.fetch_window(session, params + column_params(short), notes)
        page = Page(rows[:limit], len(rows), notes=notes)
        await self._add_columns_or_note(session, page, [c for c in columns if c not in short])
        return page

    # -- free text --------------------------------------------------------------------------

    async def text_search(self, session: SimDBSession, text: str, keys: list[str], limit: int) -> TextMatches:
        """Simulations where any of `keys` contains `text` (substring, case-insensitive).

        Each key's distinct values are checked first (cheap and cached), so an 'in' query goes
        only to keys that contain the text, or whose values could not be listed."""
        needle = text.lower()
        limiter = asyncio.Semaphore(PARALLEL_REQUESTS)

        async def may_contain(key: str) -> bool:
            async with limiter:
                try:
                    values = await self.key_values(session, key)
                except SimDBError:
                    return True
            return any(isinstance(v, str) and needle in v.lower() for v in values)

        async def query(key: str) -> tuple[str, dict | None, str | None]:
            async with limiter:
                try:
                    return key, await session.list_simulations([(key, f"in:{text}")], limit), None
                except SimDBError as exc:
                    return key, None, str(exc)

        checks = await asyncio.gather(*(may_contain(k) for k in keys))
        result = TextMatches(keys_queried=[k for k, ok in zip(keys, checks, strict=True) if ok])
        for key, data, error in await asyncio.gather(*(query(k) for k in result.keys_queried)):
            if error is not None:
                result.errors[key] = error
                continue
            if data.get("count", 0) > limit:
                result.keys_with_more.append(key)
            for row in data.get("results", []):
                uuid = clean_value(row.get("uuid"))
                match = result.matches.setdefault(uuid, {**row, "metadata": {}, "matched_keys": []})
                match["metadata"].update(metadata_dict(row.get("metadata")))
                match["matched_keys"].append(key)
        return result

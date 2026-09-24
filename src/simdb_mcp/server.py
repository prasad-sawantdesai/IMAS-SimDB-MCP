"""The MCP tools. Every tool is read-only.

Each tool checks its arguments, gets the caller's SimDB session, calls the Catalogue
(catalogue.py) and shapes the answer for the model. Where the rest lives:
client.py SimDB requests and login, query.py filter syntax, records.py value decoding,
keys.py key names and documentation, dd.py Data Dictionary lookups.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import __version__
from .auth import credentials_from_headers
from .catalogue import Catalogue, Page
from .client import (
    AuthenticationError,
    Credentials,
    NotFoundError,
    SessionPool,
    SimDBError,
    SimDBSession,
)
from .config import Settings
from .dd import DataDictionary
from .keys import collapse_keys, describe_key, key_groups, text_key_priority
from .query import CREATION_DATE, OPERATOR_HELP, Filter, simdb_datetime
from .records import clean_value, simulation_detail, simulation_summary

INSTRUCTIONS = """\
Search the IMAS SimDB simulation catalogue by metadata. All tools are read-only.

How to search well:
1. Call simdb_list_metadata_keys first. Metadata keys are free-form and differ between
   servers, so never guess a key name.
2. For categorical keys (machine, code name, workflow ...) call simdb_list_metadata_values
   to get the exact spelling before filtering.
3. Use simdb_search_simulations with structured filters. Filters are combined with AND.
   For OR, run several searches and merge the results.
4. Use simdb_search_text when you only have a word or name and do not know which key holds it.
5. Use simdb_list_recent_simulations for "latest" / "uploaded since" questions: SimDB cannot
   sort by upload date; this tool filters on it and sorts the results itself.
6. Use simdb_get_simulation for the record of one simulation (by alias or UUID); pass
   'prefixes' to get only some metadata groups.

Where the keys come from (three sources, one namespace):
- summary IDS: when a simulation is uploaded, SimDB reads the `summary` IDS of its IMAS
  output, converts it to the DD version installed on the SimDB server, and stores every node
  under its path with '/' replaced by '.' (SimDB simdb/imas/metadata.py, load_metadata).
  So `global_quantities.ip.value` is `summary/global_quantities/ip/value`.
- SimDB server: status, uploaded_by, ids, input_ids, seqid, replaced_by, alias, uuid.
- manifest: what the uploader wrote, e.g. machine, code, description (conventional) and any
  other free-form key (codeid, runfolder, ...), whose meaning SimDB does not define.
Some names (machine, pulse, code.name) exist both in the DD and as manifest keys, so such a
value may come from either.

Do not guess what a key means, its units or sign convention from its name: call
simdb_describe_keys. It combines the IMAS Data Dictionary entry (bundled with this server),
SimDB's own documentation of the keys it sets, and this server's validation rules, and says
when a key is free-form. Results also carry a 'units' map for keys that have DD units.
Metadata values are reported as stored; array values (time traces) are summarised as
min/max/first/last/n.
"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
FULL_KEY_LIST_MAX = 150  # above this, simdb_list_metadata_keys returns groups instead of keys

__all__ = ["create_server"]


def create_server(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> MCPServer:
    """Build the MCP server. `transport` replaces the network in tests."""
    pool = SessionPool(settings, transport)
    catalogue = Catalogue(settings)
    dd = DataDictionary(settings.dd_version) if settings.dd_enabled else None

    @asynccontextmanager
    async def lifespan(_server):
        # Parse the Data Dictionary in the background so the first lookup does not wait.
        _preload = asyncio.create_task(asyncio.to_thread(dd.load)) if dd is not None else None
        try:
            yield {}
        finally:
            await pool.aclose()

    mcp = MCPServer(
        name="imas-simdb",
        title="IMAS SimDB metadata search",
        instructions=INSTRUCTIONS,
        version=__version__,
        lifespan=lifespan,
    )

    # -- helpers ------------------------------------------------------------------

    def caller(ctx: Context) -> Credentials | None:
        """The caller's own credentials from the request, or None. There is no shared account:
        every user reaches SimDB as themself."""
        try:
            return credentials_from_headers(ctx.headers)
        except AuthenticationError as exc:
            raise ToolError(str(exc)) from exc

    def user_of(ctx: Context) -> str:
        credentials = caller(ctx)
        return credentials.username if credentials else "<anonymous>"

    async def session_for(ctx: Context) -> SimDBSession:
        credentials = caller(ctx)
        if credentials is None and settings.auth_mode != "none":
            raise ToolError(
                "No SimDB credentials. Configure your MCP client to send your ITER username and "
                "password as an 'Authorization: Basic ...' header (see README)."
            )
        try:
            return await pool.get(credentials)
        except SimDBError as exc:
            raise ToolError(str(exc)) from exc

    async def call(coro):
        """Await a SimDB call, turning its errors into messages for the model."""
        try:
            return await coro
        except NotFoundError as exc:
            raise ToolError(f"Not found: {exc}") from exc
        except SimDBError as exc:
            raise ToolError(str(exc)) from exc

    def page_size(limit: int | None) -> int:
        return settings.default_limit if limit is None else max(1, min(limit, settings.max_limit))

    def summaries(rows: list[dict]) -> list[dict]:
        return [simulation_summary(r, settings.dashboard_url, settings.max_value_chars) for r in rows]

    async def units_for(keys) -> dict[str, str]:
        """{key: DD units} for the summary-derived keys among `keys`."""
        if dd is None or not await asyncio.to_thread(dd.load):
            return {}
        return dd.units(sorted(set(keys)))

    async def page_response(page: Page, limit: int, page_number: int) -> dict:
        count = int(round(float(page.count)))
        response = {
            "count": count,
            "page": page_number,
            "limit": limit,
            "has_more": page_number * limit < count,
            "results": summaries(page.rows),
        }
        units = await units_for(k for r in response["results"] for k in r["metadata"])
        if units:
            response["units"] = units
        notes = list(page.notes)
        if page.approximate:
            notes.append("The count is approximate for this query on this SimDB server.")
        if notes:
            response["notes"] = notes
        return response

    # -- discovery ------------------------------------------------------------------

    @mcp.tool(title="SimDB server info", annotations=READ_ONLY)
    async def simdb_server_info(ctx: Context) -> dict:
        """Show which SimDB server this MCP talks to (URL, available API versions, server
        version) and check that your credentials are accepted."""
        session = await session_for(ctx)
        info = await call(session.server_info())
        await call(session.resolve_api_version())
        return {
            "simdb_url": settings.simdb_url,
            "api_version_used": session.api_version,
            "auth_mode": settings.auth_mode,
            "server": clean_value(info),
        }

    @mcp.tool(title="List metadata keys", annotations=READ_ONLY)
    async def simdb_list_metadata_keys(
        ctx: Context,
        prefix: Annotated[
            str | None, Field(description="Only keys under this prefix, e.g. 'code' or 'boundary'.")
        ] = None,
        name_contains: Annotated[
            str | None, Field(description="Only keys whose name contains this text (case-insensitive).")
        ] = None,
        full: Annotated[bool, Field(description="Return every key even when there are many.")] = False,
        expand_objects: Annotated[
            bool,
            Field(
                description="Also list dotted sub-keys of object-valued keys (e.g. code.name), "
                "found by sampling stored values."
            ),
        ] = True,
    ) -> dict:
        """List the metadata keys that exist in SimDB, with their value type.

        Call this before searching: keys are free-form and differ between servers.
        Without a filter on a large catalogue this returns the key groups (top-level
        prefixes with counts) and the top-level keys; call again with prefix or
        name_contains to see the keys of a group. List entries are shown once as a
        pattern such as 'code.library[*].name' (query a concrete index, e.g.
        'code.library[0].name'). Type 'Range'/'ndarray' values are searchable with
        agt/age/alt/ale. The type is taken from one stored value, so a key can hold
        other types in other simulations (e.g. a pulse stored as int or str)."""
        session = await session_for(ctx)
        keys = await call(catalogue.all_keys(session, user_of(ctx), expand_objects))
        if prefix:
            p = prefix.lower().rstrip(".")
            keys = [k for k in keys if k["name"].lower() == p or k["name"].lower().startswith((p + ".", p + "["))]
        if name_contains:
            needle = name_contains.lower()
            keys = [k for k in keys if needle in k["name"].lower()]
        collapsed = collapse_keys(keys)
        if not (full or prefix or name_contains or len(collapsed) <= FULL_KEY_LIST_MAX):
            return {
                "count": len(keys),
                "groups": key_groups(keys),
                "top_level_keys": [k for k in collapsed if "." not in k["name"]],
                "hint": "Call again with prefix='<group>' or name_contains='<text>' to list the keys of a group.",
            }
        units = await units_for(k["name"] for k in collapsed)  # dd.py ignores list indices
        for k in collapsed:
            if unit := units.get(k["name"]):
                k["units"] = unit
        return {"count": len(keys), "keys": collapsed}

    @mcp.tool(title="List values of a metadata key", annotations=READ_ONLY)
    async def simdb_list_metadata_values(
        ctx: Context,
        key: Annotated[str, Field(description="Metadata key, e.g. 'machine', 'code.name' or 'alias'.")],
        contains: Annotated[
            str | None, Field(description="Only return values containing this text (case-insensitive).")
        ] = None,
        max_values: Annotated[int, Field(ge=1, le=2000)] = 200,
    ) -> dict:
        """List the distinct values stored for one metadata key across all simulations.

        Use it to find the exact spelling of a value before filtering on it."""
        session = await session_for(ctx)
        values = [clean_value(v) for v in await call(catalogue.key_values(session, key))]
        if contains:
            needle = contains.lower()
            values = [v for v in values if needle in str(v).lower()]
        return {"key": key, "total": len(values), "truncated": len(values) > max_values, "values": values[:max_values]}

    @mcp.tool(title="Describe metadata keys", annotations=READ_ONLY)
    async def simdb_describe_keys(
        ctx: Context,
        keys: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=100,
                description="SimDB metadata keys, e.g. ['global_quantities.ip.value', 'status', 'codeid'].",
            ),
        ],
    ) -> dict:
        """Explain what SimDB metadata keys mean and where their values come from.

        For each key, combines what is known:
        - 'dd': the IMAS Data Dictionary entry when the key is a summary IDS path (SimDB stores
          the summary IDS with '/' replaced by '.'): DD path, meaning, units, type, coordinates,
          COCOS label. From the DD bundled with this server.
        - 'simdb': SimDB's own documentation for keys it sets or defines (status, uploaded_by,
          ids, alias, machine, code, description, ...).
        - 'server_rule': the rule from this SimDB server's validation schema, if it has one.
        Keys with none of these are free-form manifest metadata chosen by the uploader."""
        dd_ready = dd is not None and await asyncio.to_thread(dd.load)
        notes = []
        try:
            rules = await catalogue.validation_rules(await session_for(ctx))
        except (ToolError, SimDBError) as exc:
            rules = {}
            notes.append(f"Server validation rules not available: {exc}")
        described = {
            key: describe_key(key, dd.describe(key) if dd_ready else None, rules.get(key))
            for key in (k.strip() for k in keys)
        }
        response = {"keys": described}
        if dd_ready:
            response["dd_version"] = dd.version
            notes.append(
                "SimDB converts the summary IDS to the DD version installed on the SimDB server "
                "at upload, which may differ from dd_version."
            )
        elif dd is not None and dd.error:
            notes.append(dd.error)
        response["notes"] = notes
        return response

    # -- search -----------------------------------------------------------------------

    @mcp.tool(title="Search simulations", annotations=READ_ONLY)
    async def simdb_search_simulations(
        ctx: Context,
        filters: Annotated[
            list[Filter],
            Field(
                default_factory=list,
                description="Metadata constraints, combined with AND. Empty list returns all simulations. "
                "Operators: " + "; ".join(f"{k}: {v}" for k, v in OPERATOR_HELP.items()),
            ),
        ],
        return_keys: Annotated[
            list[str],
            Field(
                default_factory=list,
                description="Metadata keys to show in each result, e.g. ['code.name', 'codeid']. Without "
                "them the server default columns are shown (machine, pulse, code.name, status, description "
                "unless configured otherwise). Filtered keys are always included.",
            ),
        ],
        limit: Annotated[int | None, Field(description="Results per page.")] = None,
        page: Annotated[int, Field(ge=1)] = 1,
        sort_by: Annotated[str, Field(description="Metadata key to sort by. Empty keeps the server order.")] = "",
        sort_asc: bool = False,
    ) -> dict:
        """Find simulations whose metadata match all the given filters.

        Returns the total match count, one page of results (uuid, alias, date and the
        requested metadata) and whether more pages exist."""
        if sort_by.strip() in ("datetime", CREATION_DATE):
            raise ToolError("SimDB cannot sort by upload date. Use simdb_list_recent_simulations.")
        limit = page_size(limit)
        session = await session_for(ctx)
        try:
            result = await catalogue.search(
                session, filters, return_keys or settings.default_return_keys, limit, page, sort_by, sort_asc
            )
        except ValueError as exc:  # invalid filter
            raise ToolError(str(exc)) from exc
        except SimDBError as exc:
            raise ToolError(str(exc)) from exc
        return await page_response(result, limit, page)

    @mcp.tool(title="Recent simulations", annotations=READ_ONLY)
    async def simdb_list_recent_simulations(
        ctx: Context,
        since: Annotated[str, Field(description="Start of the upload-date window, YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.")],
        until: Annotated[str | None, Field(description="End of the window (exclusive). Default: now.")] = None,
        return_keys: Annotated[
            list[str] | None, Field(description="Metadata keys to show. Default: the server default columns.")
        ] = None,
        limit: Annotated[int | None, Field(description="Maximum simulations to return, newest first.")] = None,
    ) -> dict:
        """List simulations uploaded to SimDB in a date window, newest first.

        The whole window is searched and 'count' is the exact number of uploads in it, so
        there is no need to split a long window into months; use 'limit' for how many to show.

        Uses SimDB's upload date (the record's 'datetime'), not simulation metadata such as
        ids_properties.creation_date. Dates are compared in the server's time zone."""
        try:
            start, end = simdb_datetime(since), simdb_datetime(until) if until else None
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        columns = [k for k in (return_keys or settings.default_return_keys or ["status"]) if k != CREATION_DATE]
        session = await session_for(ctx)
        result = await call(catalogue.recent(session, start, end, columns, page_size(limit)))
        response = {"since": since, "until": until, "count": result.count, "results": summaries(result.rows)}
        if result.notes:
            response["notes"] = result.notes
        return response

    @mcp.tool(title="Free-text search", annotations=READ_ONLY)
    async def simdb_search_text(
        ctx: Context,
        text: Annotated[str, Field(min_length=1, description="Word or name to look for, e.g. 'JINTRAC'.")],
        keys: Annotated[
            list[str] | None,
            Field(
                description="Keys to search. Default: alias and the text-valued keys, plain descriptive keys "
                "first, list entries and '*.source' keys last."
            ),
        ] = None,
        limit: Annotated[int | None, Field(description="Maximum matches per key.")] = None,
        max_keys: Annotated[int, Field(ge=1, le=1000)] = 400,
    ) -> dict:
        """Find simulations where any text metadata value contains the given text
        (case-insensitive substring), across all text keys by default.

        SimDB has no full-text search. This first checks each key's list of distinct values
        (cheap and cached) and then runs an 'in' query only on the keys that contain the text,
        merging the results (OR across keys). Prefer simdb_search_simulations when you know the key."""
        text = text.strip()
        if ":" in text:
            raise ToolError("SimDB cannot match text containing ':'. Search for a part without ':'.")
        session = await session_for(ctx)
        if keys is None:
            keys = await call(catalogue.text_keys(session, user_of(ctx)))
        keys, skipped = keys[:max_keys], keys[max_keys:]
        limit = page_size(limit)
        found = await catalogue.text_search(session, text, keys, limit)
        if found.errors and not found.matches and len(found.errors) == len(found.keys_queried):
            raise ToolError("All searches failed: " + "; ".join(f"{k}: {v}" for k, v in found.errors.items()))

        results = []
        for row in found.matches.values():
            summary = simulation_summary(row, settings.dashboard_url, settings.max_value_chars)
            results.append({**summary, "matched_keys": row["matched_keys"]})
        response = {
            "text": text,
            "count": len(results),
            "results": results,
            "keys_with_matches": sorted({k for r in results for k in r["matched_keys"]}, key=text_key_priority),
            "keys_checked_count": len(keys),
            "keys_queried_count": len(found.keys_queried),
        }
        if found.keys_with_more:
            response["keys_with_more_matches"] = found.keys_with_more
            response["hint_more"] = (
                "Some keys have more matches than 'limit'; use simdb_search_simulations "
                "with an 'in' filter on that key to page through them."
            )
        if skipped:
            response["keys_not_searched_count"] = len(skipped)
            response["keys_not_searched_sample"] = skipped[:10]
            response["hint_not_searched"] = "Raise max_keys or pass keys=[...] to search these too."
        if found.errors:
            response["keys_failed"] = found.errors
            if any("HTTP 500" in e for e in found.errors.values()):
                response["hint_failed"] = (
                    "HTTP 500 on a key usually means some simulations store numbers "
                    "in it; SimDB cannot substring-search those keys."
                )
        return response

    # -- single simulation --------------------------------------------------------------

    @mcp.tool(title="Get simulation", annotations=READ_ONLY)
    async def simdb_get_simulation(
        ctx: Context,
        simulation: Annotated[str, Field(description="Simulation alias or UUID.")],
        include_files: Annotated[bool, Field(description="Include the input/output file list (can be long).")] = False,
        prefixes: Annotated[
            list[str] | None,
            Field(
                description="Only return metadata keys under these prefixes, e.g. ['code', 'global_quantities']. "
                "A full record can hold hundreds of keys; omit to get everything."
            ),
        ] = None,
    ) -> dict:
        """Get the metadata record of one simulation, with its parent and child simulations.

        The response lists 'metadata_groups' (top-level prefixes with key counts) so you can
        ask again for just the groups you need with 'prefixes'."""
        session = await session_for(ctx)
        detail = simulation_detail(
            await call(session.get_simulation(simulation.strip())), include_files, settings.dashboard_url
        )
        meta = detail["metadata"]
        detail["metadata_groups"] = key_groups([{"name": k} for k in meta])
        if prefixes:
            wanted = [p.strip().rstrip(".") for p in prefixes if p.strip()]
            detail["metadata"] = {
                k: v for k, v in meta.items() if any(k == p or k.startswith((p + ".", p + "[")) for p in wanted)
            }
        if units := await units_for(detail["metadata"]):
            detail["units"] = units
            detail["dd_version"] = dd.version
        return detail

    @mcp.tool(title="Get simulation provenance", annotations=READ_ONLY)
    async def simdb_get_simulation_trace(
        ctx: Context,
        simulation: Annotated[str, Field(description="Simulation alias or UUID.")],
    ) -> dict:
        """Get the status history of a simulation and the chain of simulations it replaces
        or is replaced by."""
        session = await session_for(ctx)
        return clean_value(await call(session.get_trace(simulation.strip())))

    # -- extras -------------------------------------------------------------------------

    @mcp.resource("simdb://query-operators", name="SimDB query operators", mime_type="text/markdown")
    def query_operators() -> str:
        """Reference of SimDB metadata query operators."""
        lines = ["# SimDB query operators", "", "Filters are combined with AND. String comparisons ignore case.", ""]
        lines += [f"- `{op}`: {text}" for op, text in OPERATOR_HELP.items()]
        lines += ["", "Values containing ':' cannot be matched (SimDB limitation)."]
        return "\n".join(lines)

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__, "simdb_url": settings.simdb_url})

    return mcp

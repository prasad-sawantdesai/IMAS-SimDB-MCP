"""HTTP client for the SimDB remote REST API (read-only endpoints only).

Authentication follows the SimDB CLI (``simdb/cli/remote_api.py``):

* ``f5``: POST basic-auth credentials to ``<scheme>://<host>/my.policy`` to obtain
  F5 firewall cookies, then send API requests with those cookies only. This is
  how ``simdb.iter.org`` is accessed; it does not accept SimDB tokens.
* ``basic``: send HTTP basic auth with every API request (servers using the
  LDAP / Active Directory authenticators without a firewall in front).
* ``none``: no credentials.

One logged-in ``httpx.AsyncClient`` is cached per user, so the F5 login happens
once per session TTL rather than on every tool call.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from .config import Settings

USER_AGENT = "it_script_basic"  # the value the SimDB CLI sends; the F5 policy expects it

LIMIT_HEADER = "simdb-result-limit"
PAGE_HEADER = "simdb-page"
SORT_BY_HEADER = "simdb-sort-by"
SORT_ASC_HEADER = "simdb-sort-asc"

# API versions whose read endpoints this client understands, lowest first. v1.2 and
# v1.3 share /metadata, /simulations, /simulation/<id> and /trace/<id>
# (simdb/remote/apis/v1_3/simulations.py inherits the v1.2 GET handlers).
SUPPORTED_API_VERSIONS = ("v1.2", "v1.3")


class SimDBError(Exception):
    """A request to SimDB failed."""


class SimDBTimeout(SimDBError):
    """SimDB did not answer within the configured timeout."""


class AuthenticationError(SimDBError):
    """Credentials are missing or were rejected."""


class NotFoundError(SimDBError):
    """The requested simulation or key does not exist."""


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str

    @property
    def cache_key(self) -> str:
        # Keyed on username *and* password so a wrong password never reuses a
        # session opened with the right one.
        digest = hashlib.sha256(f"{self.username}\0{self.password}".encode()).hexdigest()
        return f"{self.username}:{digest}"

    def __repr__(self) -> str:  # never print the password
        return f"Credentials(username={self.username!r})"


class SimDBSession:
    """An authenticated connection to one SimDB server for one user."""

    def __init__(
        self,
        settings: Settings,
        credentials: Credentials | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._credentials = credentials
        auth = None
        if settings.auth_mode == "basic" and credentials is not None:
            auth = httpx.BasicAuth(credentials.username, credentials.password)
        self._http = httpx.AsyncClient(
            auth=auth,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
            timeout=settings.timeout,
            verify=settings.verify,
            follow_redirects=True,
            transport=transport,
        )
        self._login_lock = asyncio.Lock()
        self._logins = 0  # number of successful firewall logins; 0 = not logged in yet
        self._api_version: str | None = None if settings.api_version == "auto" else settings.api_version

    @property
    def root_url(self) -> str:
        return f"{self._settings.simdb_url}/"

    @property
    def api_version(self) -> str | None:
        return self._api_version

    async def resolve_api_version(self) -> str:
        """Pick the highest API version offered by both the server and this client,
        as the SimDB CLI does (simdb/cli/remote_api.py, select_api_version)."""
        if self._api_version is None:
            root = await self.get_json("", versioned=False)
            offered = [str(e).rstrip("/").rsplit("/", 1)[-1] for e in root.get("endpoints", [])]
            common = [v for v in SUPPORTED_API_VERSIONS if v in offered]
            if not common:
                raise SimDBError(
                    f"No compatible SimDB API version: the server offers {', '.join(offered) or 'none'}, "
                    f"this MCP supports {', '.join(SUPPORTED_API_VERSIONS)}."
                )
            self._api_version = common[-1]
        return self._api_version

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- authentication -------------------------------------------------

    async def _f5_login(self) -> None:
        if self._credentials is None:
            raise AuthenticationError("No SimDB credentials were provided.")
        parts = urlsplit(self._settings.simdb_url)
        policy_url = f"{parts.scheme}://{parts.netloc}/my.policy"
        self._http.cookies.clear()
        try:
            res = await self._http.post(policy_url, auth=(self._credentials.username, self._credentials.password))
        except httpx.HTTPError as exc:
            raise SimDBError(f"Could not reach the SimDB firewall at {policy_url}: {exc}") from exc
        if res.status_code != 200:
            raise AuthenticationError(
                f"F5 firewall login failed (HTTP {res.status_code}). Check username and password."
            )
        # The F5 answers 200 with an HTML page even when the login is refused, so
        # confirm the cookies work the same way the SimDB CLI does: the API root
        # must return JSON.
        check = await self._http.get(self.root_url)
        if not _is_json(check):
            raise AuthenticationError("F5 firewall login failed. Check username and password.")
        self._logins += 1

    async def ensure_logged_in(self) -> None:
        """Log in to the firewall if this session has not yet (f5 mode only)."""
        if self._settings.auth_mode == "f5" and self._logins == 0:
            await self._login_unless_done_since(0)

    async def _login_unless_done_since(self, logins_seen: int) -> None:
        """Log in, unless another request already did after we saw `logins_seen` logins.
        This keeps concurrent requests that all hit an expired session to one login."""
        async with self._login_lock:
            if self._logins == logins_seen:
                await self._f5_login()

    # -- requests ---------------------------------------------------------

    async def get_json(
        self,
        path: str,
        params: list[tuple[str, str]] | None = None,
        headers: dict[str, str] | None = None,
        versioned: bool = True,
    ) -> Any:
        await self.ensure_logged_in()
        url = self.root_url + (f"{await self.resolve_api_version()}/{path}" if versioned else path)
        logins_seen = self._logins
        res = await self._send(url, params, headers)
        expired = res.status_code == 401 or (res.status_code == 200 and not _is_json(res))
        if self._settings.auth_mode == "f5" and expired:
            # The firewall session expired (401, or its HTML login page): log in again once and retry.
            await self._login_unless_done_since(logins_seen)
            res = await self._send(url, params, headers)
        return _decode(res, url)

    async def _send(self, url, params, headers) -> httpx.Response:
        try:
            return await self._http.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise SimDBTimeout(f"SimDB did not answer within {self._settings.timeout}s.") from exc
        except httpx.HTTPError as exc:
            raise SimDBError(f"Could not reach SimDB at {url}: {exc}") from exc

    # -- API endpoints (all GET) -----------------------------------------------

    async def server_info(self) -> dict:
        return await self.get_json("", versioned=False)

    async def list_metadata_keys(self) -> list[dict]:
        return await self.get_json("metadata")

    async def list_metadata_values(self, key: str) -> list:
        return await self.get_json("metadata/" + quote(key, safe=""))

    async def list_simulations(
        self,
        params: list[tuple[str, str]],
        limit: int,
        page: int = 1,
        sort_by: str = "",
        sort_asc: bool = False,
    ) -> dict:
        headers = {
            LIMIT_HEADER: str(limit),
            PAGE_HEADER: str(page),
            SORT_BY_HEADER: sort_by,
            SORT_ASC_HEADER: "true" if sort_asc else "false",
        }
        return await self.get_json("simulations", params=params, headers=headers)

    async def validation_schema(self) -> list:
        """The server's metadata validation rules (Cerberus schemas)."""
        return await self.get_json("validation_schema")

    async def get_simulation(self, ref: str) -> dict:
        return await self.get_json("simulation/" + quote(ref, safe="/"))

    async def get_trace(self, ref: str) -> dict:
        return await self.get_json("trace/" + quote(ref, safe="/"))


def _is_json(res: httpx.Response) -> bool:
    try:
        res.json()
    except ValueError:
        return False
    return True


def _decode(res: httpx.Response, url: str) -> Any:
    if res.status_code == 200:
        try:
            return res.json()
        except ValueError as exc:
            raise SimDBError(f"SimDB returned a response that is not JSON ({url}).") from exc
    try:
        body = res.json()
        message = body.get("error") or body.get("message") or str(body)
    except (ValueError, AttributeError):
        # HTML error pages from the web server or firewall: report the status, not the markup.
        message = f"{res.reason_phrase} ({url})"
    if res.status_code == 401:
        raise AuthenticationError(f"SimDB rejected the credentials: {message}")
    if res.status_code == 404:
        raise NotFoundError(message)
    raise SimDBError(f"SimDB returned HTTP {res.status_code}: {message}")


class SessionPool:
    """Caches one logged-in ``SimDBSession`` per user, with a TTL and a size cap.

    Sessions that leave the cache are closed after a grace period, not at once, because a
    request that picked the session up just before it expired may still be using it."""

    CLOSE_GRACE_SECONDS = 120.0

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport
        self._sessions: OrderedDict[str, tuple[SimDBSession, float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, credentials: Credentials | None) -> SimDBSession:
        key = credentials.cache_key if credentials else "<anonymous>"
        now = time.monotonic()
        to_close: list[SimDBSession] = []
        async with self._lock:
            entry = self._sessions.get(key)
            if entry and entry[1] > now:
                self._sessions.move_to_end(key)
                session = entry[0]
            else:
                if entry:
                    to_close.append(self._sessions.pop(key)[0])
                session = SimDBSession(self._settings, credentials, self._transport)
                self._sessions[key] = (session, now + self._settings.session_ttl)
                while len(self._sessions) > self._settings.max_sessions:
                    to_close.append(self._sessions.popitem(last=False)[1][0])
        for old in to_close:
            self._close_later(old)
        try:
            await session.ensure_logged_in()
        except AuthenticationError:
            await self.discard(key)
            raise
        return session

    def _close_later(self, session: SimDBSession) -> None:
        loop = asyncio.get_running_loop()
        loop.call_later(self.CLOSE_GRACE_SECONDS, lambda: loop.create_task(session.aclose()))

    async def discard(self, key: str) -> None:
        async with self._lock:
            entry = self._sessions.pop(key, None)
        if entry:
            await entry[0].aclose()

    async def aclose(self) -> None:
        async with self._lock:
            sessions = [s for s, _ in self._sessions.values()]
            self._sessions.clear()
        for session in sessions:
            await session.aclose()

"""The ASGI web app: one SimDB catalogue at /mcp, or several at /mcp/<name>.

With several catalogues (SIMDB_CATALOGUES), each one gets its own MCP server, built exactly
as for a single catalogue, with its own SimDB sessions and caches. A small dispatcher sends
/mcp/<name> to the right one and answers /healthz for all of them.

The dispatcher must also start every catalogue's app: each MCP app starts its session manager
in its ASGI lifespan (mcp/server/lowlevel/server.py, streamable_http_app), and a mounted
Starlette sub-app's lifespan is never run.
"""

from __future__ import annotations

from contextlib import AsyncExitStack

import httpx
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse, PlainTextResponse

from . import __version__
from .config import Settings, load_catalogues
from .dd import DataDictionary
from .server import create_server


def _transport_security(settings: Settings) -> TransportSecuritySettings | None:
    if not settings.allowed_hosts:
        return None
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.allowed_hosts + ["127.0.0.1:*", "localhost:*"],
        allowed_origins=settings.allowed_origins,
    )


def _mcp_app(server, path: str, settings: Settings):
    # Stateless + JSON responses: any worker or replica can answer any request,
    # so the service can run behind a load balancer without sticky sessions.
    return server.streamable_http_app(
        streamable_http_path=path,
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(settings),
        host=settings.host,
    )


def build_app(settings: Settings, transports: dict[str, httpx.AsyncBaseTransport] | None = None):
    """The app for `settings`. `transports` ({catalogue name: transport}) replaces the network in tests."""
    transports = transports or {}
    if not settings.catalogues_file:
        server = create_server(settings, transports.get(""))
        return _mcp_app(server, settings.path, settings)

    catalogues = load_catalogues(settings.catalogues_file, settings)
    dd = DataDictionary(settings.dd_version) if settings.dd_enabled else None  # parsed once, shared
    apps = {}
    for name, catalogue_settings in catalogues.items():
        server = create_server(catalogue_settings, transports.get(name), catalogue_name=name, dd=dd)
        apps[name] = _mcp_app(server, f"/mcp/{name}", catalogue_settings)
    return CatalogueRouter(apps, catalogues)


class CatalogueRouter:
    """ASGI app sending /mcp/<name> to that catalogue's MCP app."""

    def __init__(self, apps: dict, catalogues: dict[str, Settings]) -> None:
        self.apps = apps
        self.catalogues = catalogues

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/healthz":
            response = JSONResponse(
                {
                    "status": "ok",
                    "version": __version__,
                    "catalogues": {name: s.simdb_url for name, s in self.catalogues.items()},
                }
            )
        else:
            parts = path.split("/")  # "/mcp/itpa" -> ["", "mcp", "itpa"]
            app = self.apps.get(parts[2]) if len(parts) >= 3 and parts[1] == "mcp" else None
            if app is not None:
                await app(scope, receive, send)
                return
            known = ", ".join(f"/mcp/{name}" for name in self.apps)
            response = PlainTextResponse(f"Not found. Catalogues: {known}", status_code=404)
        await response(scope, receive, send)

    async def _lifespan(self, scope, receive, send) -> None:
        """Run every catalogue app's start-up and shutdown inside this app's lifespan."""
        message = await receive()  # lifespan.startup
        async with AsyncExitStack() as stack:
            try:
                for app in self.apps.values():
                    await stack.enter_async_context(app.router.lifespan_context(app))
            except Exception as exc:
                await send({"type": "lifespan.startup.failed", "message": str(exc)})
                return
            await send({"type": "lifespan.startup.complete"})
            message = await receive()  # lifespan.shutdown
        if message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})


def app():
    """App factory for `uvicorn --factory` and for multiple workers."""
    return build_app(Settings.from_env())


__all__ = ["app", "build_app"]

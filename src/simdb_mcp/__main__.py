"""Command line entry point: ``simdb-mcp serve`` runs the shared streamable-HTTP server."""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys

import uvicorn

from .app import build_app
from .config import Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="simdb-mcp", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the shared streamable-HTTP MCP server.")
    serve.add_argument("--host", help="Bind address (default: MCP_HOST or 127.0.0.1).")
    serve.add_argument("--port", type=int, help="Port (default: MCP_PORT or 8000).")
    serve.add_argument("--workers", type=int, default=1)
    serve.add_argument("--ssl-certfile")
    serve.add_argument("--ssl-keyfile")
    serve.add_argument("--proxy-headers", action="store_true", help="Trust X-Forwarded-* from the reverse proxy.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # it logs every request URL at INFO

    env = Settings.from_env()
    settings = dataclasses.replace(env, host=args.host or env.host, port=args.port or env.port)
    options = {
        "host": settings.host,
        "port": settings.port,
        "ssl_certfile": args.ssl_certfile,
        "ssl_keyfile": args.ssl_keyfile,
        "proxy_headers": args.proxy_headers,
        "log_level": "info",
    }
    if args.workers > 1:
        # Each worker process builds its own app from the environment.
        uvicorn.run("simdb_mcp.app:app", factory=True, workers=args.workers, **options)
    else:
        uvicorn.run(build_app(settings), **options)


if __name__ == "__main__":
    main()

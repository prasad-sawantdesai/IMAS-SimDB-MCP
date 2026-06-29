"""Program 1: verify PostgreSQL connectivity."""

from __future__ import annotations

import os

import psycopg


def main() -> None:
    database_url = os.getenv("SIMDB_MCP_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("Set SIMDB_MCP_DATABASE_URL or DATABASE_URL.")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_database(), current_user, inet_server_addr(), "
                "inet_server_port(), version()"
            )
            database, user, host, port, version = cur.fetchone()

    print("PostgreSQL connection OK")
    print(f"database: {database}")
    print(f"user: {user}")
    print(f"server: {host}:{port}")
    print(f"version: {version}")


if __name__ == "__main__":
    main()

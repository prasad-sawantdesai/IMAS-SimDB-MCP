"""Program 2: verify pgvector and the search table."""

from __future__ import annotations

import os

import psycopg


def main() -> None:
    database_url = os.getenv("SIMDB_MCP_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("Set SIMDB_MCP_DATABASE_URL or DATABASE_URL.")

    table_name = os.getenv("SIMDB_MCP_SEARCH_TABLE", "simulation_embeddings_test")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regtype('vector')")
            vector_type = cur.fetchone()[0]

            cur.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
            extension = cur.fetchone()

            cur.execute("SELECT to_regclass(%s)", (table_name,))
            table = cur.fetchone()[0]

    print(f"vector type: {vector_type or 'missing'}")
    print(f"pgvector extension: {extension[0] if extension else 'missing'}")
    print(f"search table {table_name!r}: {table or 'missing'}")


if __name__ == "__main__":
    main()

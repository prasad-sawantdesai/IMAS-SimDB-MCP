"""Program 3: create and seed a tiny pgvector test table."""

from __future__ import annotations

import os

import psycopg
from psycopg.sql import Identifier, SQL


def main() -> None:
    database_url = os.getenv("SIMDB_MCP_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("Set SIMDB_MCP_DATABASE_URL or DATABASE_URL.")

    table_name = os.getenv("SIMDB_MCP_SEARCH_TABLE", "simulation_embeddings_test")
    dimension = int(os.getenv("SIMDB_MCP_TEST_DIM", "3"))

    if dimension < 1:
        raise SystemExit("SIMDB_MCP_TEST_DIM must be positive.")

    vector = "[" + ",".join(["0.1", "0.2", "0.3"][:dimension]) + "]"
    if dimension > 3:
        vector = "[" + ",".join(["0.1", "0.2", "0.3"] + ["0"] * (dimension - 3)) + "]"

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {table} (
                        simulation_uuid uuid PRIMARY KEY,
                        alias text,
                        content text NOT NULL,
                        metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                        embedding vector({dimension}) NOT NULL
                    )
                    """
                ).format(table=Identifier(table_name), dimension=SQL(str(dimension)))
            )
            cur.execute(
                SQL(
                    """
                    INSERT INTO {table} (
                        simulation_uuid, alias, content, metadata, embedding
                    )
                    VALUES (
                        '00000000-0000-0000-0000-000000000001',
                        'mcp-smoke-test-001',
                        'ITER smoke test simulation with core_profiles temperature',
                        '{{"code.name": "ITER", "ids": "core_profiles"}}'::jsonb,
                        %s::vector
                    )
                    ON CONFLICT (simulation_uuid) DO UPDATE SET
                        alias = EXCLUDED.alias,
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding
                    """
                ).format(table=Identifier(table_name)),
                (vector,),
            )
        conn.commit()

    print(f"Seeded {table_name} with one {dimension}-dimension embedding row.")


if __name__ == "__main__":
    main()

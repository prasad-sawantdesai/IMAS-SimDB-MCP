"""Program 4: call the Python PostgreSQL search backend directly."""

from __future__ import annotations

import json
import os

from imas_simdb_mcp.config import Settings
from imas_simdb_mcp.postgres import PostgresVectorSearch


def main() -> None:
    database_url = os.getenv("SIMDB_MCP_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("Set SIMDB_MCP_DATABASE_URL or DATABASE_URL.")

    table_name = os.getenv("SIMDB_MCP_SEARCH_TABLE", "simulation_embeddings_test")
    embedding = [
        float(value)
        for value in os.getenv("SIMDB_MCP_TEST_EMBEDDING", "0.1,0.2,0.3").split(",")
    ]

    backend = PostgresVectorSearch(
        Settings(database_url=database_url, search_table=table_name)
    )
    results = backend.search_simulations(
        query_embedding=embedding,
        limit=5,
        metadata_filters={"code.name": "ITER"},
    )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

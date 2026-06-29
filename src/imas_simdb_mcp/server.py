"""MCP server exposing one SimDB pgvector search tool."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import load_settings
from .postgres import PostgresVectorSearch

mcp = FastMCP("imas-simdb-mcp")


@mcp.tool()
def search_simulations(
    query_embedding: list[float],
    limit: int | None = None,
    metadata_filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search SimDB simulations by pgvector similarity.

    Args:
        query_embedding: Embedding vector for the user's search text. The embedding
            model and dimensionality must match the stored `embedding` column.
        limit: Maximum number of matches to return. The server clamps this to its
            configured maximum.
        metadata_filters: Optional exact-match filters against metadata JSON keys,
            for example {"code.name": "ITER"}.
    """

    backend = PostgresVectorSearch(load_settings())
    return backend.search_simulations(
        query_embedding=query_embedding,
        limit=limit,
        metadata_filters=metadata_filters,
    )


def main() -> None:
    """Run the MCP server over stdio."""

    mcp.run()


if __name__ == "__main__":
    main()

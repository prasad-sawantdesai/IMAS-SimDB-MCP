"""LLM function-call wrapper for the SimDB search tool."""

from __future__ import annotations

from typing import Any

from .config import load_settings
from .postgres import PostgresVectorSearch

SEARCH_SIMULATIONS_FUNCTION = {
    "name": "search_simdb_simulations",
    "description": "Search SimDB simulations using a PostgreSQL pgvector index.",
    "parameters": {
        "type": "object",
        "properties": {
            "query_embedding": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Embedding vector matching the database embedding model.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum number of simulations to return.",
            },
            "metadata_filters": {
                "type": "object",
                "additionalProperties": True,
                "description": "Exact-match filters against metadata JSON keys.",
            },
        },
        "required": ["query_embedding"],
    },
}


def call_search_simdb_simulations(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute the LLM function call against PostgreSQL."""

    backend = PostgresVectorSearch(load_settings())
    return backend.search_simulations(
        query_embedding=arguments["query_embedding"],
        limit=arguments.get("limit"),
        metadata_filters=arguments.get("metadata_filters"),
    )

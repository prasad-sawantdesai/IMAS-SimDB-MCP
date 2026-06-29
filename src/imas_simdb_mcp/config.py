"""Runtime configuration for the SimDB MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Database settings loaded from environment variables."""

    database_url: str
    search_table: str = "simulation_embeddings"
    default_limit: int = 10
    max_limit: int = 50


def load_settings() -> Settings:
    """Load settings from environment variables."""

    database_url = os.getenv("SIMDB_MCP_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "Set SIMDB_MCP_DATABASE_URL or DATABASE_URL to a PostgreSQL connection URL."
        )

    return Settings(
        database_url=database_url,
        search_table=os.getenv("SIMDB_MCP_SEARCH_TABLE", "simulation_embeddings"),
        default_limit=int(os.getenv("SIMDB_MCP_DEFAULT_LIMIT", "10")),
        max_limit=int(os.getenv("SIMDB_MCP_MAX_LIMIT", "50")),
    )

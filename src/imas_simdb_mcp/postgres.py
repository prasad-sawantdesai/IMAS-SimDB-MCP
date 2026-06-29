"""PostgreSQL + pgvector search backend."""

from __future__ import annotations

import json
import re
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.sql import Identifier, SQL

from .config import Settings

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _vector_literal(values: list[float]) -> str:
    if not values:
        raise ValueError("query_embedding must contain at least one value.")

    return "[" + ",".join(str(float(value)) for value in values) + "]"


def _metadata_filter_sql(filters: dict[str, Any]) -> tuple[SQL, list[Any]]:
    """Build JSONB metadata filters.

    Filters are exact equality checks against the `metadata` JSONB column. This keeps
    the first version deliberately small; richer SimDB-style operators can be added
    without changing the MCP tool contract.
    """

    if not filters:
        return SQL(""), []

    clauses: list[SQL] = []
    params: list[Any] = []
    for key, value in filters.items():
        clauses.append(SQL("metadata ->> %s = %s"))
        params.extend([key, str(value)])

    return SQL(" WHERE ") + SQL(" AND ").join(clauses), params


class PostgresVectorSearch:
    """Search SimDB simulation embeddings stored in PostgreSQL."""

    def __init__(self, settings: Settings):
        if not _IDENTIFIER_RE.match(settings.search_table):
            raise ValueError("SIMDB_MCP_SEARCH_TABLE must be a simple SQL identifier.")
        self._settings = settings

    def search_simulations(
        self,
        query_embedding: list[float],
        limit: int | None = None,
        metadata_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return nearest simulations using pgvector cosine distance."""

        effective_limit = min(
            max(1, limit or self._settings.default_limit), self._settings.max_limit
        )
        vector = _vector_literal(query_embedding)
        where_sql, params = _metadata_filter_sql(metadata_filters or {})

        query = SQL(
            """
            SELECT
                simulation_uuid,
                alias,
                content,
                metadata,
                embedding <=> %s::vector AS distance
            FROM {table}
            {where}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """
        ).format(
            table=Identifier(self._settings.search_table),
            where=where_sql,
        )

        with psycopg.connect(self._settings.database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(query, [vector, *params, vector, effective_limit])
                rows = cur.fetchall()

        return [self._serialize_row(row) for row in rows]

    @staticmethod
    def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
        metadata = row.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        distance = row.get("distance")
        return {
            "simulation_uuid": str(row.get("simulation_uuid")),
            "alias": row.get("alias"),
            "content": row.get("content"),
            "metadata": metadata,
            "distance": float(distance) if distance is not None else None,
        }

"""SimDB query syntax: turning filters into `GET /simulations` query parameters.

Every parameter is ``<metadata key>=[operator:]value``. Several parameters are combined
with AND, and a parameter with an empty value only asks for that key as a result column
(SimDB simdb/query.py and docs/reference/query-operators.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Operator = Literal["eq", "ne", "in", "ni", "gt", "ge", "lt", "le", "agt", "age", "alt", "ale", "exist"]

OPERATOR_HELP = {
    "eq": "equal (case-insensitive for strings); the default",
    "ne": "not equal",
    "in": "contains the value as a substring (case-insensitive)",
    "ni": "does not contain the value as a substring",
    "gt": "greater than (for array values some servers require every element to match; prefer agt)",
    "ge": "greater than or equal",
    "lt": "less than (for array values prefer alt)",
    "le": "less than or equal",
    "agt": "array/range values (e.g. a time trace): some value is greater than the given value",
    "age": "array/range values: some value is greater than or equal",
    "alt": "array/range values: some value is less than the given value",
    "ale": "array/range values: some value is less than or equal",
    "exist": "the key is present, whatever its value (no value needed)",
}

# The upload date of a simulation record. It is not a metadata key: SimDB treats this
# filter name specially and parses the value as '%Y-%m-%d %H:%M:%S', with the colons written
# as underscores (simdb/database/database.py, _get_metadata).
CREATION_DATE = "creation_date"
DATE_OPERATORS = {"eq", "ne", "gt", "ge", "lt", "le"}


def simdb_datetime(text: str) -> str:
    """Convert '2026-09-14' or '2026-09-14T08:30' to SimDB's '2026-09-14 08_30_00'."""
    try:
        value = datetime.fromisoformat(text.strip().replace("Z", "+00:00").replace("_", ":"))
    except ValueError as exc:
        raise ValueError(f"Cannot read date {text!r}; use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.") from exc
    return value.replace(tzinfo=None).strftime("%Y-%m-%d %H_%M_%S")


class Filter(BaseModel):
    """One metadata constraint. All filters in a search are combined with AND."""

    key: str = Field(
        description="Metadata key. Nested keys use dots, e.g. 'code.name'. "
        "Use simdb_list_metadata_keys to find valid keys. 'alias' and 'uuid' are also accepted, and "
        "'creation_date' filters on the upload date (value YYYY-MM-DD[THH:MM:SS], ops eq/ne/gt/ge/lt/le)."
    )
    op: Operator = Field("eq", description="Comparison operator.")
    value: str | int | float | bool | None = Field(
        None, description="Value to compare against. Not needed for 'exist'."
    )

    @field_validator("key")
    @classmethod
    def _strip_key(cls, key: str) -> str:
        key = key.strip()
        if not key:
            raise ValueError("key must not be empty")
        return key

    def to_param(self) -> tuple[str, str]:
        """The (name, value) query parameter for this filter. Raises ValueError if SimDB cannot express it."""
        if self.op == "exist":
            return self.key, "exist:"
        if self.value is None or str(self.value) == "":
            raise ValueError(f"Filter on '{self.key}' with operator '{self.op}' needs a value.")
        if self.key == CREATION_DATE:
            if self.op not in DATE_OPERATORS:
                raise ValueError(f"'creation_date' supports {sorted(DATE_OPERATORS)}, not '{self.op}'.")
            return self.key, f"{self.op}:{simdb_datetime(str(self.value))}"
        value = str(self.value).lower() if isinstance(self.value, bool) else str(self.value)
        if ":" in value:
            # SimDB splits the value on every ':' (simdb/query.py, parse_query_arg) and rejects it.
            raise ValueError(
                f"SimDB cannot match values containing ':' (got {value!r} for '{self.key}'). "
                "Use op='in' with a part of the value that has no ':'."
            )
        return self.key, f"{self.op}:{value}"


def build_params(filters: list[Filter]) -> list[tuple[str, str]]:
    return [f.to_param() for f in filters]


def column_params(keys: list[str]) -> list[tuple[str, str]]:
    """Parameters that only ask for these keys as result columns."""
    return [(k, "") for k in keys]

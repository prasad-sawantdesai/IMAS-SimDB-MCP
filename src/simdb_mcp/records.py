"""Turning SimDB's JSON records into compact, plain values for the model."""

from __future__ import annotations

import array
import base64
import binascii
import math
from typing import Any

# numpy dtype name -> Python array typecode, for the arrays SimDB sends as raw bytes.
_ARRAY_TYPECODES = {
    "float64": "d",
    "float32": "f",
    "int64": "q",
    "int32": "i",
    "int16": "h",
    "int8": "b",
    "uint64": "Q",
    "uint32": "I",
    "uint16": "H",
    "uint8": "B",
}
_FILE_FIELDS = ("type", "uri", "checksum", "datetime", "usage", "purpose", "access")


def summarise_array(value: dict) -> dict:
    """Summarise a numpy array that SimDB sent as base64 bytes (simdb/json.py, CustomEncoder).

    Returns n, min, max, first and last of the non-NaN elements instead of the whole array,
    to keep responses small. Values are as stored; no unit or sign convention is applied."""
    summary: dict[str, Any] = {"array": True, "dtype": value.get("dtype")}
    typecode = _ARRAY_TYPECODES.get(str(value.get("dtype")))
    try:
        raw = base64.b64decode(value.get("bytes") or "")
    except (binascii.Error, ValueError):
        return summary
    if typecode is None or len(raw) % array.array(typecode).itemsize:
        return summary
    data = array.array(typecode, raw)
    numbers = [v for v in data if not (isinstance(v, float) and math.isnan(v))]
    summary["n"] = len(data)
    if numbers:
        summary.update(min=min(numbers), max=max(numbers), first=numbers[0], last=numbers[-1])
    return summary


def clean_value(value: Any) -> Any:
    """Replace SimDB's typed JSON objects (UUIDs, numpy arrays) with plain values."""
    if isinstance(value, dict):
        kind = value.get("_type")
        if kind == "uuid.UUID":
            return value.get("hex")
        if kind == "numpy.ndarray":
            return summarise_array(value)
        return {k: clean_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_value(v) for v in value]
    return value


def metadata_dict(metadata: Any) -> dict[str, Any]:
    """Metadata as {key: value}. SimDB sends it as [{"element": key, "value": v}, ...]."""
    if isinstance(metadata, dict):
        return clean_value(metadata)
    return {
        item["element"]: clean_value(item.get("value"))
        for item in metadata or []
        if isinstance(item, dict) and "element" in item
    }


def shorten(value: Any, max_chars: int | None) -> Any:
    """Cut long text (e.g. multi-line descriptions) for list views."""
    if max_chars and isinstance(value, str) and len(value) > max_chars:
        return f"{value[:max_chars]}… [{len(value)} chars; full text via simdb_get_simulation]"
    return value


def simulation_summary(item: dict, dashboard_url: str | None = None, max_chars: int | None = None) -> dict:
    """uuid, alias, upload date and metadata of one simulation, for result lists."""
    uuid = clean_value(item.get("uuid"))
    summary = {
        "uuid": uuid,
        "alias": item.get("alias"),
        "datetime": item.get("datetime"),
        "metadata": {k: shorten(v, max_chars) for k, v in metadata_dict(item.get("metadata")).items()},
    }
    if dashboard_url and uuid:
        summary["dashboard_url"] = dashboard_url.format(uuid=uuid)
    return summary


def simulation_detail(data: dict, include_files: bool, dashboard_url: str | None = None) -> dict:
    """The full record of one simulation: summary, file counts (or files), parents and children."""
    detail = simulation_summary(data, dashboard_url)
    for side in ("inputs", "outputs"):
        files = data.get(side) or []
        detail[f"{side}_count"] = len(files)
        if include_files:
            detail[side] = [{k: clean_value(f[k]) for k in _FILE_FIELDS if f.get(k) not in (None, "")} for f in files]
    for relation in ("parents", "children"):
        if relation in data:
            detail[relation] = [clean_value(r) for r in data[relation] or []]
    return detail

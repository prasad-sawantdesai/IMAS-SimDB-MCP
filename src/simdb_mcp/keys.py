"""Everything about metadata key names.

SimDB keeps metadata from three sources in one namespace:

* the `summary` IDS of the simulation's IMAS output, stored under its node paths with '/'
  replaced by '.' (SimDB simdb/imas/metadata.py, load_metadata), e.g.
  `global_quantities.ip.value` is `summary/global_quantities/ip/value`;
* keys the SimDB server sets itself (status, uploaded_by, ids, ...);
* the manifest written by the uploader: a few conventional keys (machine, code,
  description) and any number of free-form ones.

This module holds SimDB's own documentation of its keys (sources: SimDB 0.15.2 code and
docs, cited per entry), reads the server's validation rules, and combines those with the
Data Dictionary (dd.py) into one description per key. It also has the helpers for key
names: list indices, grouping and the order used by free-text search.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

_LIST_INDEX = re.compile(r"\[(\d+|\*)\]")  # [3], or the pattern [*]


def without_indices(key: str) -> str:
    """'code.library[3].name' or 'code.library[*].name' -> 'code.library.name'."""
    return _LIST_INDEX.sub("", key)


def key_pattern(key: str) -> str:
    """'code.library[3].name' -> 'code.library[*].name'."""
    return _LIST_INDEX.sub("[*]", key)


def collapse_keys(keys: list[dict]) -> list[dict]:
    """One entry per list pattern (code.library[*].name) with the number of indices, sorted by name."""
    merged: dict[str, dict] = {}
    for key in keys:
        pattern = key_pattern(key["name"])
        entry = merged.setdefault(pattern, {**key, "name": pattern})
        if pattern != key["name"]:
            entry["indexed"] = entry.get("indexed", 0) + 1
    return sorted(merged.values(), key=lambda k: k["name"])


def top_level(key: str) -> str:
    return key.split(".", 1)[0].split("[", 1)[0]


def key_groups(keys: list[dict]) -> dict[str, int]:
    """Number of keys under each top-level name."""
    return dict(sorted(Counter(top_level(k["name"]) for k in keys).items()))


def text_key_priority(key: str) -> tuple:
    """Sort order for free-text search: plain descriptive keys first; list entries and
    '*.source' notes (where a name is unlikely) last."""
    return ("[" in key, key.endswith(".source"), key.count("."), key)


# -- SimDB's documentation of its keys ------------------------------------------------------

SERVER = "set by the SimDB server"
MANIFEST = "manifest metadata (conventional SimDB field)"

SIMDB_KEYS: dict[str, dict[str, str]] = {
    "alias": {
        "origin": SERVER,
        "meaning": "Name of the simulation, unique on the server. If the uploaded alias ends with "
        "'-' or '#', the server appends the next free number (see seqid).",
        "source": "simdb/remote/apis/v1_2/simulations.py (_set_alias)",
    },
    "uuid": {
        "origin": SERVER,
        "meaning": "Unique identifier of the simulation record.",
        "source": "simdb/database/models/simulation.py",
    },
    "status": {
        "origin": SERVER,
        "meaning": "Validation state: 'not validated' on upload, then 'accepted', 'passed' or "
        "'failed' after validation, 'deprecated' when replaced by another simulation, or "
        "'deleted'.",
        "source": "simdb/database/models/simulation.py (Simulation.Status)",
    },
    "uploaded_by": {
        "origin": SERVER,
        "meaning": "User who uploaded the simulation (user name or e-mail of the authenticated user).",
        "source": "simdb/remote/apis/v1_2/simulations.py (post)",
    },
    "ids": {
        "origin": SERVER,
        "meaning": "IDSs found in the simulation's IMAS outputs, as '[ids/occurrence, ...]'.",
        "source": "simdb/database/models/simulation.py (from_manifest)",
    },
    "input_ids": {
        "origin": SERVER,
        "meaning": "IDSs found in the simulation's IMAS inputs, as '[ids/occurrence, ...]'.",
        "source": "simdb/database/models/simulation.py (from_manifest)",
    },
    "seqid": {
        "origin": SERVER,
        "meaning": "Sequence number the server appended to the alias.",
        "source": "simdb/remote/apis/v1_2/simulations.py (_set_alias)",
    },
    "replaces": {
        "origin": "manifest or upload option",
        "meaning": "Alias or UUID of the older simulation this one supersedes; the server then marks "
        "that one 'deprecated' and sets its replaced_by.",
        "source": "simdb/remote/apis/v1_2/simulations.py (post); simdb/cli/commands/simulation.py",
    },
    "replaced_by": {
        "origin": SERVER,
        "meaning": "UUID of the newer simulation that superseded this one.",
        "source": "simdb/remote/apis/v1_2/simulations.py (post)",
    },
    "replaces_reason": {
        "origin": "uploaded metadata (SimDB only reads it)",
        "meaning": "Why this simulation replaces the older one (shown in the provenance trace).",
        "source": "simdb/remote/apis/v1_2/simulations.py (_build_trace)",
    },
    "replaced_on": {
        "origin": "uploaded metadata (SimDB only reads it)",
        "meaning": "When this simulation was superseded (shown as deprecated_on in the trace).",
        "source": "simdb/remote/apis/v1_2/simulations.py (_build_trace)",
    },
    "machine": {
        "origin": MANIFEST,
        "meaning": "Device the simulation is for. Expected by most servers. The summary IDS also has "
        "a 'machine' node (DD 4.1+), so the value may come from either.",
        "source": "docs/reference/manifest-format.md",
    },
    "code": {
        "origin": MANIFEST,
        "meaning": "Code that produced the simulation (code.name, code.version, ...). Expected by most "
        "servers. The summary IDS also has code/*, so values may come from either.",
        "source": "docs/reference/manifest-format.md",
    },
    "description": {
        "origin": MANIFEST,
        "meaning": "Free-text description of the run, written by the uploader.",
        "source": "docs/reference/manifest-format.md",
    },
    "responsible_name": {
        "origin": "manifest (top-level field)",
        "meaning": "Person responsible for the simulation.",
        "source": "docs/reference/manifest-format.md",
    },
    "creation_date": {
        "origin": "not stored as metadata",
        "meaning": "Special filter name for the upload date of the record; use it in filters or "
        "simdb_list_recent_simulations.",
        "source": "simdb/database/database.py (_get_metadata)",
    },
}

FREE_FORM = {
    "origin": "manifest metadata (free-form)",
    "meaning": "Not defined by SimDB or the IMAS Data Dictionary: chosen by the uploader. Check "
    "'server_rule' if present, the stored values, or ask the data provider.",
}


def simdb_key_info(key: str) -> dict[str, str] | None:
    """SimDB's own documentation for a key, matching 'code.name' to 'code' as well."""
    return SIMDB_KEYS.get(key) or SIMDB_KEYS.get(top_level(key))


# -- the server's validation rules ----------------------------------------------------------


def flatten_schema(schemas: Any) -> dict[str, dict]:
    """Validation rules per dotted key from the server's Cerberus schemas.

    Nested 'dict' rules with a 'schema' are flattened: {'code': {'schema': {'name': ...}}}
    gives rules for 'code' and 'code.name'."""
    rules: dict[str, dict] = {}

    def walk(prefix: str, schema: dict) -> None:
        for name, rule in schema.items():
            if not isinstance(rule, dict):
                continue
            key = f"{prefix}.{name}" if prefix else name
            rules[key] = {k: v for k, v in rule.items() if k != "schema"}
            if isinstance(rule.get("schema"), dict):
                walk(key, rule["schema"])

    for schema in schemas if isinstance(schemas, list) else [schemas]:
        if isinstance(schema, dict):
            walk("", schema)
    return rules


# -- one description per key -----------------------------------------------------------------


def describe_key(key: str, dd_entry: dict | None, rule: dict | None) -> dict:
    """Combine what is known about a key: its origin, the Data Dictionary entry, SimDB's
    documentation and the server's validation rule."""
    simdb = simdb_key_info(key)
    if simdb:
        info: dict = {"origin": simdb["origin"], "simdb": simdb}
    elif dd_entry:
        info = {"origin": "summary IDS of the simulation's IMAS output"}
    else:
        info = dict(FREE_FORM)
    if dd_entry:
        info["dd"] = dd_entry
    if rule:
        info["server_rule"] = rule
    return info

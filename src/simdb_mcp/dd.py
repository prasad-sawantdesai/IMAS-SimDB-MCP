"""IMAS Data Dictionary entries for summary-derived SimDB keys, offline via IMAS-Python.

A SimDB key maps back to a `summary` path by replacing '.' with '/' and dropping list
indices (see keys.py):

    global_quantities.ip.value   ->  summary/global_quantities/ip/value
    code.library[2].version      ->  summary/code/library/version
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import Any

from .keys import without_indices

log = logging.getLogger(__name__)


class DataDictionary:
    """Describes `summary` IDS paths for one DD version. Loads lazily; safe to share between threads."""

    def __init__(self, version: str | None = None) -> None:
        self._requested_version = version
        self._lock = threading.Lock()
        self._summary = None  # IMAS-Python metadata tree of the summary IDS
        self._entries: dict[str, dict[str, Any] | None] = {}
        self.version: str | None = None
        self.error: str | None = None

    def load(self) -> bool:
        """Parse the DD once (about a second). Returns False if it is not available."""
        with self._lock:
            if self._summary is None and self.error is None:
                try:
                    import imas

                    version = self._requested_version or imas.dd_zip.latest_dd_version()
                    self._summary = imas.IDSFactory(version).new("summary").metadata
                    self.version = version
                except Exception as exc:  # package missing, unknown version, ...
                    self.error = f"IMAS Data Dictionary not available: {exc}"
                    log.warning(self.error)
            return self._summary is not None

    def describe(self, key: str) -> dict[str, Any] | None:
        """The DD entry for a SimDB key, or None when the key is not a `summary` path."""
        if not self.load():
            return None
        path = without_indices(key).replace(".", "/")
        if path not in self._entries:
            self._entries[path] = self._entry(path)
        return self._entries[path]

    def units(self, keys) -> dict[str, str]:
        """{key: units} for the keys that are `summary` paths with units."""
        return {key: entry["units"] for key in keys if (entry := self.describe(key)) and entry.get("units")}

    def _entry(self, path: str) -> dict[str, Any] | None:
        try:
            node = self._summary[path]
        except (KeyError, ValueError):
            return None
        # summary quantities are structures like ip/{value, source}: the meaning and the COCOS
        # label are on the structure, while the 'value' leaf is only documented as "Value".
        parent = None
        if path.endswith("/value"):
            with contextlib.suppress(KeyError, ValueError):
                parent = self._summary[path.rsplit("/", 1)[0]]
        documentation = (parent.documentation if parent else node.documentation) or ""
        data_type = node.data_type.name
        entry: dict[str, Any] = {
            "dd_path": f"summary/{path}",
            "type": data_type if data_type.startswith("STRUCT") else f"{data_type}_{node.ndim}D",
            "units": node.units or None,
            "documentation": " ".join(documentation.split()),
        }
        if node.coordinates:
            entry["coordinates"] = [str(c) for c in node.coordinates]
        # IMAS-Python only sets this attribute on COCOS-dependent nodes.
        cocos = getattr(node, "cocos_label_transformation", None) or getattr(parent, "cocos_label_transformation", None)
        if cocos:
            entry["cocos_label"] = cocos
        return entry

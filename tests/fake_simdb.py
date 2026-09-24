"""An in-memory SimDB server behind a fake F5 firewall, for the tests.

It imitates the SimDB 0.15 behaviour the MCP depends on or works around:

* F5 login: POST /my.policy with basic auth sets a cookie; a refused login is HTML with
  status 200, and requests without a valid cookie get the HTML login page.
* The root lists the API versions (production lists v1, v1.1 and v1.2).
* GET /simulations: constraints with an empty value are dropped (so `exist` is ignored), and
  when result columns are requested, paging and the count are computed over
  (simulation x key) rows, which gives fractional counts.
* The special filter `creation_date` compares the upload date.
* Numpy arrays are sent as base64 bytes.

Metadata mixes a nested object (`code`, as newer servers store it) with flat keys such as
`global_quantities.ip.value` (as SimDB 0.15 stores the summary IDS), so both are exercised.
"""

from __future__ import annotations

import array
import asyncio
import base64
import json

import httpx

BASE = "https://simdb.example.org/scenarios/api"
USERNAME, PASSWORD = "alice", "s3cret"
API_PREFIX = "/scenarios/api"


def numpy_array(values: list[float]) -> dict:
    """A float64 array as SimDB 0.15 sends it (simdb/json.py, CustomEncoder)."""
    raw = array.array("d", values).tobytes()
    return {"_type": "numpy.ndarray", "dtype": "float64", "bytes": base64.b64encode(raw).decode()}


def uuid(hex_char: str) -> dict:
    return {"_type": "uuid.UUID", "hex": hex_char * 32}


SIMULATIONS = [
    {
        "uuid": uuid("a"),
        "alias": "100001/1",
        "datetime": "2025-01-10T10:00:00",
        "metadata": {
            "machine": "ITER",
            "code": {"name": "JINTRAC", "version": "2.1"},
            "pulse": 100001,
            "status": "passed",
            "description": "ITER baseline 15MA DT scenario",
            "time": {"min": 0.0, "max": 400.0},
            "global_quantities.ip.value": numpy_array([-1.0e6, -1.5e7, float("nan"), -1.4e7]),
        },
        "outputs": [{"type": "IMAS", "uri": "imas:hdf5?path=/work/a", "checksum": "x", "datetime": "2025-01-10"}],
    },
    {
        "uuid": uuid("b"),
        "alias": "100002/1",
        "datetime": "2025-02-10T10:00:00",
        "metadata": {
            "machine": "ITER",
            "code": {"name": "METIS", "version": "1.0"},
            "pulse": 100002,
            "status": "failed",
            "description": "Hydrogen PFPO scenario",
            "time": {"min": 0.0, "max": 20.0},
        },
        "outputs": [],
    },
    {
        "uuid": uuid("c"),
        "alias": "west-55000",
        "datetime": "2025-03-10T10:00:00",
        "metadata": {
            "machine": "WEST",
            "code": {"name": "JINTRAC", "version": "2.2"},
            "pulse": 55000,
            "status": "passed",
            "description": "WEST L-mode",
            "time": {"min": 1.0, "max": 8.0},
        },
        "outputs": [],
    },
]

METADATA_KEYS = [
    {"name": "machine", "type": "string"},
    {"name": "code", "type": "object"},
    {"name": "pulse", "type": "number"},
    {"name": "status", "type": "string"},
    {"name": "description", "type": "string"},
    {"name": "time", "type": "Range"},
    {"name": "global_quantities.ip.value", "type": "ndarray"},
]

# Shaped like SimDB's validation/iter_scenarios_validation.yaml: a list of Cerberus schemas.
VALIDATION_SCHEMA = [
    {
        "machine": {"required": True, "type": "string"},
        "code": {"required": True, "type": "dict", "schema": {"name": {"required": True, "type": "string"}}},
        "global_quantities": {
            "type": "dict",
            "schema": {"ip": {"type": "dict", "schema": {"value": {"type": "numpy", "ge": -17000000, "le": 0}}}},
        },
    }
]


def lookup(metadata: dict, key: str) -> tuple[object, bool]:
    """(value, found) for a flat key or a dotted path into nested objects."""
    if key in metadata:
        return metadata[key], True
    value = metadata
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None, False
        value = value[part]
    return value, True


def matches(sim: dict, key: str, expression: str) -> bool:
    """Whether a simulation satisfies one `key=[op:]value` constraint."""
    *operator, target = expression.split(":")
    if len(operator) > 1:
        raise ValueError(f"Malformed query string {target}.")  # what SimDB does with ':' in values
    op = operator[0] if operator else "eq"
    if key == "creation_date":
        when = target.replace("_", ":").replace(" ", "T")
        return compare(op, sim["datetime"], when)
    if key == "uuid":
        return sim["uuid"]["hex"] == target
    value, found = (sim["alias"], True) if key == "alias" else lookup(sim["metadata"], key)
    if op == "exist":
        return found
    if not found:
        return False
    if op in ("agt", "age", "alt", "ale"):  # ranges: compare against max or min
        bound = value["max"] if op in ("agt", "age") else value["min"]
        return compare(op[1:], bound, float(target))
    if op in ("gt", "ge", "lt", "le"):
        return compare(op, float(value), float(target))
    text, target = str(value).lower(), target.lower()
    return {"eq": text == target, "ne": text != target, "in": target in text, "ni": target not in text}[op]


def compare(op: str, a, b) -> bool:
    return {"eq": a == b, "ne": a != b, "gt": a > b, "ge": a >= b, "lt": a < b, "le": a <= b}[op]


def find_simulation(ref: str) -> dict | None:
    return next((s for s in SIMULATIONS if ref in (s["alias"], s["uuid"]["hex"])), None)


class FakeSimDB:
    """Pass `transport()` to the code under test; inspect `requests` and `login_count` afterwards."""

    def __init__(self) -> None:
        self.versions = ["v1", "v1.1", "v1.2"]  # what simdb.iter.org lists
        self.require_login = True  # False: a SimDB without authentication
        self.cookie: str | None = None  # the firewall session cookie currently valid
        self.login_count = 0
        self.values_requests = 0  # calls to /metadata/<key>
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def expire_session(self) -> None:
        """The firewall forgets the current session, as it does after its timeout."""
        self.cookie = None

    async def handle(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0)  # let concurrent requests overlap, as over a network
        self.requests.append(request)
        path = request.url.path
        if path == "/my.policy":
            return self.login(request)
        if self.require_login and (self.cookie is None or self.cookie not in request.headers.get("cookie", "")):
            return httpx.Response(200, text="<html>F5 login page</html>")
        if path.rstrip("/") == API_PREFIX:
            return httpx.Response(200, json={"endpoints": [f"{BASE}/{v}" for v in self.versions]})

        version, _, route = path[len(API_PREFIX) + 1 :].partition("/")
        if version not in self.versions:
            return httpx.Response(404, text="<html><title>404 Not Found</title></html>")
        if route == "metadata":
            return httpx.Response(200, json=METADATA_KEYS)
        if route.startswith("metadata/"):
            return self.key_values(route.removeprefix("metadata/"))
        if route == "validation_schema":
            return httpx.Response(200, json=VALIDATION_SCHEMA)
        if route == "simulations":
            return self.simulations(request)
        if route.startswith(("simulation/", "trace/")):
            kind, _, ref = route.partition("/")
            return self.simulation(ref) if kind == "simulation" else self.trace(ref)
        return httpx.Response(404, json={"error": "no such endpoint"})

    def login(self, request: httpx.Request) -> httpx.Response:
        expected = "Basic " + base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
        if request.headers.get("authorization") != expected:
            return httpx.Response(200, text="<html>Access denied</html>")  # the F5 refuses with 200
        self.login_count += 1
        self.cookie = f"MRHSession=s{self.login_count}"  # each login gets a new session
        return httpx.Response(200, headers={"set-cookie": f"{self.cookie}; Path=/"}, text="<html>ok</html>")

    def key_values(self, key: str) -> httpx.Response:
        if key == "alias":
            return httpx.Response(200, json=[s["alias"] for s in SIMULATIONS])
        self.values_requests += 1
        values = []
        for sim in SIMULATIONS:
            value, found = lookup(sim["metadata"], key)
            value = json.dumps(value) if isinstance(value, dict) else value
            if found and value not in values:
                values.append(value)
        return httpx.Response(200, json=values)

    def simulations(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params.multi_items()
        columns = [k for k, _ in params if k not in ("alias", "uuid")]  # every named key is a column
        constraints = [(k, v) for k, v in params if v.split(":")[-1]]  # empty values are dropped
        try:
            selected = [s for s in SIMULATIONS if all(matches(s, k, v) for k, v in constraints)]
        except ValueError as exc:
            return httpx.Response(400, json={"error": str(exc)})
        limit = int(request.headers.get("simdb-result-limit", 100))
        page = int(request.headers.get("simdb-page", 1))

        if not columns:
            shown = selected[(page - 1) * limit : page * limit] if limit else selected
            results = [{"uuid": s["uuid"], "alias": s["alias"], "datetime": s["datetime"]} for s in shown]
            return httpx.Response(200, json={"count": len(selected), "page": page, "limit": limit, "results": results})

        # One row per (simulation, column present); page and count over rows.
        rows = [(s, k, v) for s in selected for k in columns for v, found in [lookup(s["metadata"], k)] if found]
        per_page = limit * len(columns)
        shown = rows[(page - 1) * per_page : page * per_page] if limit else rows
        results: dict[str, dict] = {}
        for sim, key, value in shown:
            entry = results.setdefault(
                sim["uuid"]["hex"],
                {"uuid": sim["uuid"], "alias": sim["alias"], "datetime": sim["datetime"], "metadata": []},
            )
            entry["metadata"].append({"element": key, "value": value})
        count = len(rows) / len(columns)
        return httpx.Response(
            200, json={"count": count, "page": page, "limit": limit, "results": list(results.values())}
        )

    def simulation(self, ref: str) -> httpx.Response:
        sim = find_simulation(ref)
        if sim is None:
            return httpx.Response(400, json={"error": f"Simulation {ref} not found."})
        metadata = [{"element": k, "value": v} for k, v in sim["metadata"].items()]
        record = {k: sim[k] for k in ("uuid", "alias", "datetime", "outputs")}
        return httpx.Response(200, json={**record, "inputs": [], "metadata": metadata, "parents": [], "children": []})

    def trace(self, ref: str) -> httpx.Response:
        sim = find_simulation(ref)
        if sim is None:
            return httpx.Response(400, json={"error": f"Simulation {ref} not found."})
        return httpx.Response(
            200, json={"uuid": sim["uuid"], "alias": sim["alias"], "status": sim["metadata"]["status"]}
        )

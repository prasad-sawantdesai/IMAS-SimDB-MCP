# Development

## Set up

```bash
git clone https://github.com/prasad-sawantdesai/IMAS-SimDB-MCP
cd IMAS-SimDB-MCP
uv venv -p 3.12 && uv pip install -e ".[test,docs,lint]"
```

Without uv: `python3 -m venv .venv && .venv/bin/pip install -e ".[test,docs,lint]"`.

## Lint and format

```bash
.venv/bin/ruff check .          # add --fix to apply safe fixes
.venv/bin/ruff format .         # the formatter decides the layout; do not fight it
```

The rules are in `[tool.ruff]` in `pyproject.toml`.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull request:

| Job | Checks |
|---|---|
| lint | `ruff check` and `ruff format --check` |
| test | `pytest` on Python 3.11, 3.12 and 3.13 |
| docs | the Sphinx build, with warnings as errors (as on Read the Docs) |
| docker | the image builds and the container answers `/healthz` |

## Code layout

| File | Responsibility |
|---|---|
| `server.py` | The MCP tools: check arguments, call the catalogue, shape the answer. Also the instructions sent to the model. |
| `catalogue.py` | How to search SimDB: paging strategies, date windows, free text, result columns, caches. |
| `client.py` | HTTP requests to SimDB, F5 login, API version, per-user session pool. |
| `keys.py` | Key names, SimDB's documentation of its keys, server validation rules. |
| `dd.py` | IMAS Data Dictionary lookups via IMAS-Python. |
| `query.py` | Filters to SimDB query syntax. |
| `records.py` | SimDB JSON to compact values: UUIDs, arrays, long text, file lists. |
| `auth.py` | Credentials from the `Authorization` header. |
| `config.py` | Settings from environment variables. |
| `__main__.py` | The `simdb-mcp serve` command. |

## Tests

```bash
.venv/bin/pytest
```

The tests never contact a real SimDB. `tests/fake_simdb.py` is an in-memory server that
behaves like SimDB 0.15 behind the F5 firewall: firewall login, row-based paging and
fractional counts, dropped `exist` constraints, `creation_date`, numpy arrays as bytes and
a validation schema.

| File | Covers |
|---|---|
| `tests/test_client.py` | Login, session reuse and expiry, API version selection, errors. |
| `tests/test_helpers.py` | Filters, value decoding, key names, credentials, settings. |
| `tests/test_server.py` | Every tool, in process and over real HTTP with an `Authorization` header. |

To check a running server against real SimDB:

```bash
.venv/bin/simdb-mcp serve --port 8000
.venv/bin/python scripts/test_all_tools.py http://127.0.0.1:8000/mcp --text JINTRAC
```

`scripts/fetch_api_spec.py` saves the server's OpenAPI description, to compare the tools with
the deployed API.

## Documentation

```bash
.venv/bin/sphinx-build -W docs docs/_build/html
```

Pages are Markdown (MyST) in `docs/`. Read the Docs builds them with `.readthedocs.yaml`.

## Adding a tool

1. Put the SimDB logic in `catalogue.py` (or `client.py` for a new endpoint).
2. Add the tool in `server.py` with `annotations=READ_ONLY`, a docstring that tells the model
   when to use it, and `Field` descriptions for each argument.
3. Add a test in `tests/test_server.py`, extending `tests/fake_simdb.py` if needed.
4. Add it to [Tools](tools.md).

Only read endpoints may be used; the server must never change SimDB.

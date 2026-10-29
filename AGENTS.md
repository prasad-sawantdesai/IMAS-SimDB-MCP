# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex, Copilot, …) working on this
repository. Humans: see `docs/development.md`.

## What this is

A read-only MCP server that lets AI assistants search the IMAS SimDB catalogue by metadata.
Python 3.11+, MCP Python SDK 2.x (`MCPServer`), httpx, IMAS-Python for the Data Dictionary.
Production target: `https://simdb.iter.org/scenarios/api`, SimDB API v1.2 behind an F5 firewall.

## Commands

```bash
uv venv -p 3.12 && uv pip install -e ".[test,docs,lint]"   # set up
.venv/bin/ruff check . && .venv/bin/ruff format .          # lint and format
.venv/bin/pytest                                           # all tests, ~5 s, no network
.venv/bin/pytest tests/test_server.py -k recent            # one area
.venv/bin/sphinx-build -W docs docs/_build/html            # docs, warnings are errors
.venv/bin/simdb-mcp serve --port 8000                      # run locally
```

## How to work here

1. **Understand first.** Read the module docstring of the file you change; `catalogue.py`
   explains the SimDB quirks the code works around. Find the test that covers the behaviour.
2. **Plan small.** One behaviour per change. Keep tool names and response keys stable:
   MCP clients and the model's instructions depend on them.
3. **Change the code in the right place** (see Layout). Tools stay thin; logic goes in
   `catalogue.py`, SimDB HTTP in `client.py`.
4. **Test the behaviour, not the implementation.** Add or update a test in `tests/`, extending
   `tests/fake_simdb.py` if SimDB behaves in a new way. A test must fail when the behaviour
   breaks: break the code on purpose once to check.
5. **Verify before saying done:** `ruff check .`, `ruff format --check .`, `pytest`, and the
   docs build if `docs/` or a docstring shown in the docs changed. Report failures as they are.
6. **Update the docs** in the same change: `docs/tools.md` for tool behaviour,
   `docs/configuration.md` for settings, `docs/how-it-works.md` for design decisions.

## Layout

| Change | Where |
|---|---|
| A tool's arguments, description or answer shape | `src/simdb_mcp/server.py` (also `INSTRUCTIONS` there) |
| The web app, several catalogues at `/mcp/<name>` | `src/simdb_mcp/app.py` |
| How searching works, caches, SimDB workarounds | `src/simdb_mcp/catalogue.py` |
| SimDB requests, F5 login, API version, sessions | `src/simdb_mcp/client.py` |
| Filter syntax / decoding SimDB JSON | `query.py` / `records.py` |
| Key names, SimDB's documentation of its keys | `keys.py` |
| Data Dictionary lookups | `dd.py` |
| Settings | `config.py`, plus `docs/configuration.md` and `deploy/simdb-mcp.env.example` |

## Hard rules

- **Read-only.** Only call SimDB read endpoints (GET). Never add upload, patch, delete or
  watcher calls.
- **Credentials.** Every request uses the caller's own `Authorization: Basic` credentials.
  No shared or service account. Never log, print, store or commit passwords, tokens or
  `SIMDB_BASIC_AUTH` values; `Credentials.__repr__` must not show the password.
- **Cite SimDB when working around it.** A workaround comment names the SimDB file and
  function it depends on (e.g. `simdb/database/database.py, _get_simulation_data`), and the
  fake server imitates that behaviour.
- **Small answers.** Tool responses go into the model's context: summarise arrays, shorten long
  text, return groups before long lists. Check response sizes with `scripts/test_all_tools.py`.
- **No network in tests.** Tests use `FakeSimDB`; never call a real SimDB from `tests/`.

## IMAS accuracy

- Do not infer IMAS semantics (meaning, units, coordinates, sign/COCOS conventions) from a key
  name. Verify against the IMAS Data Dictionary: `DataDictionary` in `dd.py` (IMAS-Python), or
  the IMAS DD MCP (`https://imas-dd.iter.org/mcp`) if your client has it.
- State which DD version a fact comes from. SimDB converts the `summary` IDS to the DD version
  installed on the SimDB server, which may differ.
- Distinguish documented facts from your interpretation. If the DD or SimDB docs are silent or
  contradictory, say so and ask for an IMAS expert rather than guessing.
- When a claim rests on code, cite `path:line`.

## Gotchas

- `simdb.iter.org` runs SimDB 0.15.x: it lists API v1, v1.1, v1.2 (no v1.3) and pages
  `GET /simulations` over (simulation × key) rows. See the docstring of `catalogue.py`.
- Query values containing `:` cannot be sent to SimDB; `Filter.to_param` refuses them.
- `creation_date` is a special filter for the upload date, formatted `YYYY-MM-DD HH_MM_SS`.
- In tests, the in-process MCP `Client` runs the server lifespan on every connection, so
  sessions and caches reset between `call()`s; the real HTTP app starts once.
- `mcp` 2.x renamed `FastMCP` to `MCPServer` (`mcp.server.mcpserver`); v1 examples do not apply.

## Checking against the real SimDB

Only by hand, with the developer's own account and never in CI:

```bash
.venv/bin/simdb-mcp serve --port 8000
.venv/bin/python scripts/test_all_tools.py http://127.0.0.1:8000/mcp --text JINTRAC
```

## Git

Work on a branch; CI (`.github/workflows/ci.yml`: lint, tests on 3.11–3.13, docs, Docker)
must pass. Keep commits focused and say *why* in the message.

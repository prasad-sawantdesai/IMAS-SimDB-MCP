# IMAS SimDB MCP

[![CI](https://github.com/prasad-sawantdesai/IMAS-SimDB-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/prasad-sawantdesai/IMAS-SimDB-MCP/actions/workflows/ci.yml)

An [MCP](https://modelcontextprotocol.io) server that lets AI assistants such as Claude
search the [IMAS SimDB](https://simdb.readthedocs.io/) simulation catalogue by metadata.

- **Read-only.** It uses the existing SimDB REST API and never changes anything in SimDB.
- **Per user.** Each person connects with their own ITER account; there is no shared account.
- **Explains the data.** Metadata keys taken from the `summary` IDS are described from the
  IMAS Data Dictionary (units, meaning, sign conventions), bundled with the server.

Full documentation is in [`docs/`](docs/index.md) and is built for Read the Docs.

## Use it (Claude Code)

Your administrator gives you the server URL. Then:

```bash
# once
claude mcp add-json --scope user simdb \
  '{"type":"http","url":"${SIMDB_MCP_URL}","headers":{"Authorization":"Basic ${SIMDB_BASIC_AUTH}"}}'

# in each new terminal
export SIMDB_MCP_URL=https://<server>/mcp
read -s -p "ITER password: " P; echo
export SIMDB_BASIC_AUTH=$(printf '%s:%s' "$USER" "$P" | base64 -w0); unset P
claude
```

In Claude, `/mcp` should list `simdb`. Then ask, for example: *"Find ITER JINTRAC
simulations uploaded since July"*.

## Run it (administrators)

```bash
cp deploy/simdb-mcp.env.example deploy/simdb-mcp.env   # set MCP_ALLOWED_HOSTS
docker compose up -d --build                           # MCP on 127.0.0.1:8000
curl http://127.0.0.1:8000/healthz
```

Put it behind HTTPS before anyone else connects: users' passwords travel in a request
header. See [Deployment](docs/deployment.md) for TLS, systemd and Apptainer.

## Develop

```bash
uv venv -p 3.12 && uv pip install -e ".[test,docs,lint]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .   # lint
.venv/bin/pytest                                   # tests against a fake SimDB
.venv/bin/simdb-mcp serve --port 8000              # local server
.venv/bin/python scripts/test_all_tools.py http://127.0.0.1:8000/mcp   # call every tool
.venv/bin/sphinx-build -W docs docs/_build/html    # build the documentation
```

## License

GPL-3.0, see [LICENSE](LICENSE).

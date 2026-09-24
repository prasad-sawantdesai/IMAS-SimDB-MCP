# Configuration

All settings are environment variables. With Docker or systemd they go in
`deploy/simdb-mcp.env` (start from `deploy/simdb-mcp.env.example`). Unset variables keep
the default.

## SimDB connection

| Variable | Default | Meaning |
|---|---|---|
| `SIMDB_URL` | `https://simdb.iter.org/scenarios/api` | SimDB API base URL, as used with `simdb remote config new`. |
| `SIMDB_AUTH_MODE` | `f5` | `f5`: log in through the ITER F5 firewall (simdb.iter.org). `basic`: send the credentials to SimDB directly (servers without the firewall). `none`: no login. |
| `SIMDB_API_VERSION` | `auto` | `auto` uses the highest version the server offers (v1.3, else v1.2). Or a fixed value such as `v1.2`. |
| `SIMDB_TIMEOUT` | `60` | Seconds to wait for SimDB. |
| `SIMDB_CA_BUNDLE` | – | Extra CA certificates. Not needed for simdb.iter.org. |
| `SIMDB_VERIFY_TLS` | `true` | Set `false` only for testing. |
| `SIMDB_SESSION_TTL` | `1800` | Seconds a user's SimDB login is reused. |
| `SIMDB_MAX_SESSIONS` | `500` | Most user logins kept at once. |

## Answers

| Variable | Default | Meaning |
|---|---|---|
| `SIMDB_DEFAULT_RETURN_KEYS` | `machine,pulse,code.name,status,description` | Columns shown in search results when none are asked for. Set it empty for none. |
| `SIMDB_DEFAULT_LIMIT` | `20` | Results per page by default. |
| `SIMDB_MAX_LIMIT` | `200` | Largest page size a caller may ask for. |
| `SIMDB_MAX_VALUE_CHARS` | `300` | Longer text is cut in result lists (`0` = never). |
| `SIMDB_DASHBOARD_URL` | – | Link added to each result, e.g. `https://simdb.iter.org/dashboard/uuid/{uuid}`. |
| `SIMDB_DD` | `true` | Describe keys from the IMAS Data Dictionary. |
| `SIMDB_DD_VERSION` | newest bundled | Data Dictionary version used for descriptions. |

## MCP endpoint

| Variable | Default | Meaning |
|---|---|---|
| `MCP_HOST` | `127.0.0.1` | Address to listen on (`0.0.0.0` inside a container). |
| `MCP_PORT` | `8000` | Port. |
| `MCP_PATH` | `/mcp` | URL path of the MCP endpoint. |
| `MCP_ALLOWED_HOSTS` | – | Host names users put in the URL, e.g. `simdb-mcp.iter.org,simdb-mcp.iter.org:*`. Requests with other `Host` headers are refused. |
| `MCP_ALLOWED_ORIGINS` | – | Allowed browser origins, if browsers connect directly. |

## Command line

```text
simdb-mcp serve [--host HOST] [--port PORT] [--workers N] [--proxy-headers]
                [--ssl-certfile FILE --ssl-keyfile FILE]
```

`--proxy-headers` trusts `X-Forwarded-*` headers from the reverse proxy. With `--workers`
above 1, each worker keeps its own logins and caches.

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
| `MCP_PATH` | `/mcp` | URL path of the MCP endpoint (one catalogue only; see below). |
| `MCP_ALLOWED_HOSTS` | – | Host names users put in the URL, e.g. `simdb-mcp.iter.org,simdb-mcp.iter.org:*`. Requests with other `Host` headers are refused. |
| `MCP_ALLOWED_ORIGINS` | – | Allowed browser origins, if browsers connect directly. |

## Several SimDB catalogues

One process can serve several SimDB servers, each at its own path, `/mcp/<name>`. Set
`SIMDB_CATALOGUES` to a TOML file with one table per catalogue (example:
`deploy/catalogues.toml.example`):

```toml
[iter]
url = "https://simdb.iter.org/scenarios/api"
auth_mode = "f5"
dashboard_url = "https://simdb.iter.org/dashboard/uuid/{uuid}"

[itpa]
url = "http://10.154.84.240:5400"
auth_mode = "none"
```

This serves `/mcp/iter` and `/mcp/itpa`; `/mcp` itself and `MCP_PATH` are then not used.

| Key | Required | Meaning |
|---|---|---|
| `url` | yes | SimDB API base URL, as `SIMDB_URL`. |
| `auth_mode` | no, default `f5` | As `SIMDB_AUTH_MODE`. Check the server: `curl <url>/` shows `"authentication"`; `None` means `auth_mode = "none"`. |
| `api_version`, `ca_bundle`, `verify_tls` | no | As the matching `SIMDB_*` variables. |
| `dashboard_url` | no | Dashboard link for this catalogue. Not inherited from `SIMDB_DASHBOARD_URL`. |

Catalogue names may use `a-z`, `0-9` and `-`. All other settings (limits, caches, Data
Dictionary, `MCP_*`) are shared and still come from the environment. Each catalogue keeps its
own SimDB logins and caches.

## Command line

```text
simdb-mcp serve [--host HOST] [--port PORT] [--workers N] [--proxy-headers]
                [--ssl-certfile FILE --ssl-keyfile FILE]
```

`--proxy-headers` trusts `X-Forwarded-*` headers from the reverse proxy. With `--workers`
above 1, each worker keeps its own logins and caches.

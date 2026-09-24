# Connect Claude

You need the server URL from your administrator, for example
`https://simdb-mcp.iter.org/mcp`, and your ITER username and password.

## Claude Code

Add the server once. The single quotes matter: they store the variable names, not their
values, so your password is never written to a configuration file.

```bash
claude mcp add-json --scope user simdb \
  '{"type":"http","url":"${SIMDB_MCP_URL}","headers":{"Authorization":"Basic ${SIMDB_BASIC_AUTH}"}}'
```

In every new terminal, set the two variables and start Claude:

```bash
export SIMDB_MCP_URL=https://simdb-mcp.iter.org/mcp
read -s -p "ITER password: " P; echo
export SIMDB_BASIC_AUTH=$(printf '%s:%s' "$USER" "$P" | base64 -w0); unset P
claude
```

Type `/mcp` in Claude: `simdb` should be listed as connected. Then ask in plain language:

- *Which metadata keys exist in SimDB?*
- *Find ITER JINTRAC simulations with status passed.*
- *Show the simulations uploaded last week.*
- *Which simulations reach a plasma current above 10 MA? What sign convention is used?*
- *Show the full record and provenance of 104001/11.*

To remove the server: `claude mcp remove simdb -s user`.

## Other MCP clients

Any client that can send a custom HTTP header works: use the streamable HTTP transport, the
server URL, and the header `Authorization: Basic <base64 of username:password>`. This includes
VS Code, Cursor and the MCP Inspector (`npx @modelcontextprotocol/inspector`).

Clients that only support OAuth sign-in cannot connect yet.

## Is my password safe?

Your password is sent to the MCP server with every request, the same way the `simdb`
command-line client sends it to SimDB. So:

- use the `https://` URL your administrator gives you, never a plain `http://` one;
- the server keeps your SimDB login in memory for 30 minutes so it does not log in on every
  call, and never writes passwords to disk or to its logs.

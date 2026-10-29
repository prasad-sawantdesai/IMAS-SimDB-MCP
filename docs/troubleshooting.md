# Troubleshooting

## For users

`/mcp` in Claude shows `simdb` as failed
: The server URL is wrong or the server is down. Check `SIMDB_MCP_URL`, and try
  `curl https://<server>/healthz`.

A tool answers "No SimDB credentials"
: `SIMDB_BASIC_AUTH` was not exported in the terminal where you started `claude`. Set it
  (see [Connect Claude](connect.md)) and restart `claude`.

A tool answers "F5 firewall login failed"
: Wrong username or password. Set `SIMDB_BASIC_AUTH` again and restart `claude`.

An answer seems incomplete
: Look at the `notes` in the tool result, or ask Claude to show them. They say when a count is
  approximate, a date window was too large, or some keys could not be searched.

## For administrators

Every request fails with "Could not reach SimDB"
: The host cannot reach `SIMDB_URL`. Test from the host or container with `curl`.

"No compatible SimDB API version"
: The SimDB server offers neither v1.2 nor v1.3. Ask Claude to run `simdb_server_info`, or run
  `scripts/test_all_tools.py`; both show the versions the server lists.

HTTP 421 "Invalid Host header"
: `MCP_ALLOWED_HOSTS` does not include the host name in the URL users connect to.

Searches are slow
: Wide date windows and text searches over many keys cost the most on SimDB 0.15. The first
  text search after a restart also has to read each key's values once. Timings per tool are
  shown by `scripts/test_all_tools.py`.

Key descriptions have no `dd` part
: The Data Dictionary could not be loaded. The server log says why (`IMAS Data Dictionary not
  available: ...`); usually IMAS-Python is missing or `SIMDB_DD_VERSION` is unknown.

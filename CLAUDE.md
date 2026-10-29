# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- For a change touching more than one module, or any change to a tool's answer shape, start in
  plan mode and show the plan before editing.
- To check a change end to end, the `simdb` MCP server (if configured) calls the running server
  the way users do; `/mcp` shows whether it is connected. Never put credentials in commands you
  run; the user exports `SIMDB_BASIC_AUTH` themselves.
- `/context` shows which instruction files are loaded. This file imports `AGENTS.md`, which
  holds the shared instructions for all agents: edit that file, not this one, for anything
  that is not Claude-specific.

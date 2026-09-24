# IMAS SimDB MCP

IMAS SimDB MCP is a [Model Context Protocol](https://modelcontextprotocol.io) server. It
lets AI assistants such as Claude search the [IMAS SimDB](https://simdb.readthedocs.io/)
simulation catalogue by metadata: find simulations by code, machine, plasma current, upload
date or any other stored key, read a simulation's record, and explain what a key means.

It is **read-only**: it only calls the read endpoints of the existing SimDB REST API. It
works **per user**: every request carries the user's own ITER credentials, and the server
logs in to SimDB as that user.

## Where to start

Using it
: [Connect Claude](connect.md) and the [tools](tools.md) Claude can call.

Running it
: [Deployment](deployment.md) with Docker, systemd or Apptainer, and the
  [configuration](configuration.md) settings.

Maintaining it
: [How it works](how-it-works.md) and [Development](development.md).

Something wrong?
: [Troubleshooting](troubleshooting.md).

```{toctree}
:hidden:
:caption: Use

connect
tools
```

```{toctree}
:hidden:
:caption: Run

deployment
configuration
```

```{toctree}
:hidden:
:caption: Maintain

how-it-works
development
troubleshooting
```

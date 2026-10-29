# Deployment

The server is one Python web service. Run it on a host inside the ITER network that can
reach `https://simdb.iter.org`, behind an HTTPS reverse proxy.

```text
users' MCP clients ──HTTPS──▶ nginx (TLS) ──HTTP──▶ simdb-mcp :8000 ──HTTPS──▶ simdb.iter.org
```

:::{important}
Users send their ITER password in the `Authorization` header of every request. Never
expose the plain-HTTP port outside the host; always put TLS in front.
:::

You need: a host name (for example `simdb-mcp.iter.org`), a TLS certificate for it, and one
of Docker, systemd or Apptainer.

## Docker Compose

```bash
git clone https://github.com/prasad-sawantdesai/IMAS-SimDB-MCP imas-simdb-mcp
cd imas-simdb-mcp
cp deploy/simdb-mcp.env.example deploy/simdb-mcp.env
```

Edit `deploy/simdb-mcp.env`. The one setting you must change is the public host name:

```bash
MCP_ALLOWED_HOSTS=simdb-mcp.iter.org,simdb-mcp.iter.org:*
```

Start the server and check it:

```bash
docker compose up -d --build
docker compose ps                        # "healthy" after about 30 s
curl http://127.0.0.1:8000/healthz
```

Add TLS with the bundled nginx container (skip this if the host already has a proxy; point
that proxy at `127.0.0.1:8000` using `deploy/nginx-simdb-mcp.conf` as a template):

```bash
mkdir -p deploy/certs
cp server.crt deploy/certs/server.crt
cp server.key deploy/certs/server.key
docker compose --profile tls up -d
curl https://simdb-mcp.iter.org/healthz
```

Update later with `git pull && docker compose up -d --build`.

## systemd

```bash
sudo useradd --system simdbmcp
sudo git clone https://github.com/prasad-sawantdesai/IMAS-SimDB-MCP /opt/simdb-mcp
cd /opt/simdb-mcp
sudo python3 -m venv .venv && sudo .venv/bin/pip install .
sudo mkdir -p /etc/simdb-mcp
sudo cp deploy/simdb-mcp.env.example /etc/simdb-mcp/simdb-mcp.env   # edit it
sudo cp deploy/simdb-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now simdb-mcp
sudo cp deploy/nginx-simdb-mcp.conf /etc/nginx/conf.d/                # set server_name and certificates
sudo nginx -t && sudo systemctl reload nginx
```

Python 3.11 or newer is required; on ITER hosts run `module load Python` first if needed.

## Apptainer

For hosts without Docker:

```bash
apptainer build simdb-mcp.sif deploy/simdb-mcp.def
apptainer run --env-file deploy/simdb-mcp.env simdb-mcp.sif --port 8000
```

## Check a deployment

From any machine, with your own account:

```bash
python scripts/test_all_tools.py https://simdb-mcp.iter.org/mcp --text JINTRAC
```

It calls every tool and prints PASS or FAIL per check, with the response size and time.

## Common problems when deploying

| Symptom | Cause |
|---|---|
| Build cannot download packages | The host needs a proxy: `docker compose build --build-arg HTTP_PROXY=$HTTP_PROXY --build-arg HTTPS_PROXY=$HTTPS_PROXY`. |
| Health check passes, logins fail | The container cannot reach SimDB. Test: `docker compose exec simdb-mcp python -c "import urllib.request; urllib.request.urlopen('https://simdb.iter.org/scenarios/api/')"` (a 401 error means SimDB is reachable). |
| `Invalid Host header` (HTTP 421) | `MCP_ALLOWED_HOSTS` does not match the host name in the URL. |

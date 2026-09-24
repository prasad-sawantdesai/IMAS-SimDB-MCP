FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . && useradd --system --uid 10001 simdbmcp

USER simdbmcp
# Listen on all interfaces inside the container; trust X-Forwarded-* from the proxy container.
ENV MCP_HOST=0.0.0.0 MCP_PORT=8000 FORWARDED_ALLOW_IPS=*
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/healthz'); sys.exit(0)"
CMD ["simdb-mcp", "serve", "--proxy-headers", "--workers", "2"]

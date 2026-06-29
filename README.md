# imas-simdb-mcp

Minimal MCP server for searching SimDB data through PostgreSQL + pgvector.

Full step-by-step tutorial:
[docs/simdb_mcp_pgvector_tutorial.rst](docs/simdb_mcp_pgvector_tutorial.rst).

This first version intentionally exposes one MCP tool:

```text
search_simulations(query_embedding, limit=None, metadata_filters=None)
```

The caller is responsible for creating `query_embedding` with the same embedding
model used to populate the database. PostgreSQL remains the source of truth, and
pgvector is the semantic search index inside PostgreSQL.

## Database

Create the pgvector table/index:

```bash
psql "$DATABASE_URL" -f sql/pgvector_search.sql
```

The expected table is:

```sql
simulation_embeddings(
    simulation_uuid uuid primary key,
    alias text,
    content text,
    metadata jsonb,
    embedding vector(1536)
)
```

Change `vector(1536)` if your embedding model uses a different dimension.

## Run

```bash
export SIMDB_MCP_DATABASE_URL="postgresql://user:password@host:5432/simdb"
python -m imas_simdb_mcp.server
```

or after installation:

```bash
imas-simdb-mcp
```

Optional environment variables:

```text
SIMDB_MCP_SEARCH_TABLE=simulation_embeddings
SIMDB_MCP_DEFAULT_LIMIT=10
SIMDB_MCP_MAX_LIMIT=50
```

## Tool Input Example

```json
{
  "query_embedding": [0.012, -0.004, 0.031],
  "limit": 5,
  "metadata_filters": {
    "code.name": "ITER"
  }
}
```

`metadata_filters` are exact equality checks against JSON metadata keys. Richer
SimDB-style operators can be added later without changing the tool name.

## Five Server Smoke Tests

Install first:

```bash
cd /home/ITER/sawantp1/github/imas-simdb-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
export SIMDB_MCP_DATABASE_URL="postgresql://user:password@host:5432/simdb"
```

Run these in order:

```bash
python programs/01_check_postgresql.py
python programs/02_check_pgvector.py
python programs/03_create_test_embedding_table.py
python programs/04_call_search_backend.py
python programs/05_llm_function_call.py
```

The smoke tests use `simulation_embeddings_test` by default. To test another
table:

```bash
export SIMDB_MCP_SEARCH_TABLE=simulation_embeddings
```

What each program checks:

```text
01_check_postgresql.py          PostgreSQL login/connectivity
02_check_pgvector.py            pgvector extension/type and table visibility
03_create_test_embedding_table.py creates one tiny vector test table and row
04_call_search_backend.py       Python backend search function
05_llm_function_call.py         LLM-style function schema + function execution
```

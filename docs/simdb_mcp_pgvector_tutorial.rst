SimDB MCP With PostgreSQL and pgvector
======================================

This tutorial explains the minimal path we are building in this repository:

.. code-block:: text

   LLM or MCP client
        |
        v
   imas-simdb-mcp
        |
        v
   PostgreSQL + pgvector
        |
        v
   SimDB metadata/search index

The current implementation is intentionally small. It exposes one useful search
function, proves that PostgreSQL and pgvector are reachable from the server, and
gives you a clean place to add better SimDB-aware queries later.


What You Are Building
---------------------

The first version has one MCP tool:

.. code-block:: text

   search_simulations(query_embedding, limit=None, metadata_filters=None)

It searches a PostgreSQL table that contains simulation text, metadata, and a
pgvector embedding.

Important idea:

.. code-block:: text

   PostgreSQL stores data.
   pgvector stores/searches embeddings inside PostgreSQL.
   MCP exposes the search as a tool that an LLM can call.

The MCP server does not generate embeddings yet. The caller provides
``query_embedding``. Later, we can add an embedding provider such as OpenAI,
a local model, or an ITER-hosted embedding service.


Why Start This Way
------------------

This path is good for a first working system because:

* PostgreSQL stays the main database.
* pgvector avoids a second service such as Qdrant at the beginning.
* The MCP tool contract is small and stable.
* The search implementation can later become richer without changing how the LLM
  calls the tool.
* SimDB's real schema can remain the source of truth while
  ``simulation_embeddings`` acts as a search index.


Repository Layout
-----------------

The important files are:

.. code-block:: text

   pyproject.toml
   README.md
   sql/pgvector_search.sql
   src/imas_simdb_mcp/
       config.py
       postgres.py
       server.py
       llm_function.py
   programs/
       01_check_postgresql.py
       02_check_pgvector.py
       03_create_test_embedding_table.py
       04_call_search_backend.py
       05_llm_function_call.py

What each part does:

``config.py``
  Reads database settings from environment variables.

``postgres.py``
  Contains the PostgreSQL + pgvector search backend.

``server.py``
  Starts the MCP server and exposes ``search_simulations``.

``llm_function.py``
  Defines the same search as a plain LLM function-call wrapper. This is useful
  before connecting a full MCP client.

``programs/*.py``
  Five smoke tests. Run them in order on the server.


Step 1: Install The Project
---------------------------

On the server:

.. code-block:: bash

   cd /home/ITER/sawantp1/github/imas-simdb-mcp

   python -m venv .venv
   source .venv/bin/activate

   pip install -e .

This installs the local package and its Python dependencies:

* ``mcp``
* ``psycopg[binary]``


Step 2: Configure PostgreSQL Access
-----------------------------------

Set the PostgreSQL connection string:

.. code-block:: bash

   export SIMDB_MCP_DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME"

Example:

.. code-block:: bash

   export SIMDB_MCP_DATABASE_URL="postgresql://simdb:secret@localhost:5432/simdb"

The code also accepts ``DATABASE_URL`` if ``SIMDB_MCP_DATABASE_URL`` is not set.


Step 3: Test PostgreSQL Connectivity
------------------------------------

Run:

.. code-block:: bash

   python programs/01_check_postgresql.py

Expected result:

.. code-block:: text

   PostgreSQL connection OK
   database: ...
   user: ...
   server: ...
   version: ...

If this fails, solve database access first. MCP and pgvector do not matter until
basic PostgreSQL connectivity works.


Step 4: Check pgvector
----------------------

Run:

.. code-block:: bash

   python programs/02_check_pgvector.py

Expected result after pgvector is installed:

.. code-block:: text

   vector type: vector
   pgvector extension: ...
   search table 'simulation_embeddings_test': missing

The test table can be missing at this step. Program 3 creates it.

If ``vector type`` or ``pgvector extension`` is missing, the database server does
not have pgvector enabled yet. A database administrator may need to install the
extension package. Once installed, this SQL enables it in the database:

.. code-block:: sql

   CREATE EXTENSION IF NOT EXISTS vector;


Step 5: Create A Tiny Test Search Table
---------------------------------------

Run:

.. code-block:: bash

   python programs/03_create_test_embedding_table.py

This creates and seeds:

.. code-block:: text

   simulation_embeddings_test

It uses a tiny 3-dimensional vector so you can test the whole flow without a real
embedding model.

Expected result:

.. code-block:: text

   Seeded simulation_embeddings_test with one 3-dimension embedding row.

This test table has the same logical columns as the future production table:

.. code-block:: sql

   simulation_uuid uuid PRIMARY KEY
   alias text
   content text
   metadata jsonb
   embedding vector(3)

Production will normally use a larger vector dimension, for example
``vector(1536)`` or whatever your embedding model produces.


Step 6: Test The Python Search Backend
--------------------------------------

Run:

.. code-block:: bash

   python programs/04_call_search_backend.py

Expected result:

.. code-block:: json

   [
     {
       "simulation_uuid": "00000000-0000-0000-0000-000000000001",
       "alias": "mcp-smoke-test-001",
       "content": "ITER smoke test simulation with core_profiles temperature",
       "metadata": {
         "code.name": "ITER",
         "ids": "core_profiles"
       },
       "distance": 0.0
     }
   ]

This proves:

* Python can connect to PostgreSQL.
* pgvector distance search works.
* JSON metadata filters work.
* The backend function returns LLM-friendly JSON.


Step 7: Test The LLM Function Wrapper
-------------------------------------

Run:

.. code-block:: bash

   python programs/05_llm_function_call.py

This prints:

* the function schema an LLM can use,
* the function arguments,
* the function result.

This does not call a real LLM. It simulates the final function call locally.
That is intentional: first test the deterministic function, then connect an LLM.


Step 8: Run The MCP Server
--------------------------

Run:

.. code-block:: bash

   source .venv/bin/activate
   export SIMDB_MCP_DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME"
   export SIMDB_MCP_SEARCH_TABLE="simulation_embeddings_test"

   imas-simdb-mcp

The MCP server runs over stdio. A client starts it and communicates through the
MCP protocol.

For production, use:

.. code-block:: bash

   export SIMDB_MCP_SEARCH_TABLE="simulation_embeddings"


Step 9: Create The Production pgvector Table
--------------------------------------------

For the real search index, use:

.. code-block:: bash

   psql "$SIMDB_MCP_DATABASE_URL" -f sql/pgvector_search.sql

That file creates:

.. code-block:: sql

   CREATE EXTENSION IF NOT EXISTS vector;

   CREATE TABLE IF NOT EXISTS simulation_embeddings (
       simulation_uuid uuid PRIMARY KEY,
       alias text,
       content text NOT NULL,
       metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
       embedding vector(1536) NOT NULL
   );

   CREATE INDEX IF NOT EXISTS simulation_embeddings_embedding_hnsw
       ON simulation_embeddings
       USING hnsw (embedding vector_cosine_ops);

   CREATE INDEX IF NOT EXISTS simulation_embeddings_metadata_gin
       ON simulation_embeddings
       USING gin (metadata);

Change ``vector(1536)`` if your embedding model uses a different size.


Step 10: Understand The Query
-----------------------------

The backend query is conceptually:

.. code-block:: sql

   SELECT
       simulation_uuid,
       alias,
       content,
       metadata,
       embedding <=> :query_embedding AS distance
   FROM simulation_embeddings
   WHERE metadata ->> 'code.name' = 'ITER'
   ORDER BY embedding <=> :query_embedding
   LIMIT 10;

The ``<=>`` operator is pgvector cosine distance. Lower distance means more
similar.


Step 11: Understand The Current Limitation
------------------------------------------

Right now the search index is not automatically filled from SimDB.

Current state:

.. code-block:: text

   SimDB tables/data exist separately.
   simulation_embeddings is a new search index table.
   MCP searches simulation_embeddings.

The next implementation step is an indexer:

.. code-block:: text

   read SimDB metadata
       -> flatten important fields into text
       -> create embedding
       -> insert/update simulation_embeddings

Example text to embed:

.. code-block:: text

   alias: 53298/1
   code.name: ITER
   ids: core_profiles, equilibrium, summary
   description: plasma scenario with electron temperature profiles


Step 12: How This Connects To A Real LLM
----------------------------------------

The real flow will be:

.. code-block:: text

   User asks:
       "Find ITER simulations related to core_profiles temperature"

   LLM:
       creates or requests an embedding for the question

   LLM calls MCP tool:
       search_simulations(
           query_embedding=[...],
           limit=10,
           metadata_filters={"code.name": "ITER"}
       )

   MCP:
       queries PostgreSQL + pgvector

   LLM:
       summarizes returned simulations

The MCP tool returns structured data, not prose. The LLM is responsible for the
final explanation.


Step 13: How To Improve Later
-----------------------------

Add improvements in this order:

1. Add an indexer that reads existing SimDB simulations.
2. Add real embedding generation.
3. Add SimDB-style filters such as ``gt:``, ``lt:``, ``in:``, and ``exist:``.
4. Join ``simulation_embeddings`` back to real SimDB tables for authoritative
   metadata.
5. Add a second MCP tool: ``get_simulation(simulation_uuid_or_alias)``.
6. Add hybrid search: vector similarity plus PostgreSQL full-text search.
7. Add permission checks before returning sensitive metadata.


Troubleshooting
---------------

``No module named psycopg``
  Run ``pip install -e .`` inside the virtual environment.

``Set SIMDB_MCP_DATABASE_URL or DATABASE_URL``
  Export the database URL before running programs.

``type "vector" does not exist``
  pgvector is not installed or not enabled in the database.

``expected 1536 dimensions, not 3``
  Your query vector dimension does not match the table's ``embedding`` column.

``permission denied to create extension vector``
  Ask the database administrator to install/enable pgvector.

``relation "simulation_embeddings" does not exist``
  Run ``sql/pgvector_search.sql`` or use the smoke-test table:
  ``export SIMDB_MCP_SEARCH_TABLE=simulation_embeddings_test``.


Short Videos And References
---------------------------

Video rankings change, so these links intentionally point to focused YouTube
searches rather than one fixed video:

* `Short pgvector tutorials on YouTube <https://www.youtube.com/results?search_query=pgvector+postgresql+semantic+search+tutorial+short>`__
* `MCP Python/FastMCP tutorials on YouTube <https://www.youtube.com/results?search_query=Model+Context+Protocol+Python+FastMCP+tutorial>`__
* `PostgreSQL vector search tutorials on YouTube <https://www.youtube.com/results?search_query=PostgreSQL+pgvector+embeddings+tutorial>`__

Primary references:

* `pgvector on GitHub <https://github.com/pgvector/pgvector>`__
* `Model Context Protocol documentation <https://modelcontextprotocol.io/>`__
* `MCP Python SDK on GitHub <https://github.com/modelcontextprotocol/python-sdk>`__
* `PostgreSQL documentation <https://www.postgresql.org/docs/>`__


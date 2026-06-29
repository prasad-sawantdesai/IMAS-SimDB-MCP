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

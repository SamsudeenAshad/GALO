-- GALO Postgres + pgvector schema (M1).
--
-- The embedding column dimension is templated as {EMBED_DIM} and substituted at
-- migration time from GALO_EMBED_DIM, because it MUST match the embedding
-- model's output dimension. Changing the model requires a migration + re-embed.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id            uuid PRIMARY KEY,
    title         text,
    source_uri    text,
    content_hash  text UNIQUE NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id           uuid PRIMARY KEY,
    document_id  uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ord          int  NOT NULL,
    text         text NOT NULL,
    entity_ids   uuid[] NOT NULL DEFAULT '{}',
    embedding    vector({EMBED_DIM}),
    UNIQUE (document_id, ord)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS chunks_entity_ids_gin
    ON chunks USING gin (entity_ids);

-- Ingestion run state / provenance audit trail.
CREATE TABLE IF NOT EXISTS jobs (
    id           uuid PRIMARY KEY,
    document_id  uuid,
    step         text NOT NULL,
    status       text NOT NULL,          -- pending | running | done | failed
    error        text,
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_document_id ON jobs (document_id);

-- Enable pgvector and text search extensions following TigerGraph/TigerData guides
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS issues (
    id serial PRIMARY KEY,
    source TEXT NOT NULL,
    external_key TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT DEFAULT '',
    repo TEXT,
    project TEXT,
    status TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    raw_json JSONB DEFAULT '{}'::jsonb,
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, ''))
    ) STORED,
    UNIQUE (source, external_key)
);

CREATE TABLE IF NOT EXISTS issue_vectors (
    issue_id INT PRIMARY KEY REFERENCES issues(id) ON DELETE CASCADE,
    embedding VECTOR(768) NOT NULL,
    model TEXT NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS labels (
    issue_id INT REFERENCES issues(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    source TEXT NOT NULL,
    approved BOOLEAN DEFAULT FALSE,
    ts TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS similar_issues (
    issue_id INT REFERENCES issues(id) ON DELETE CASCADE,
    neighbor_id INT NOT NULL,
    score REAL NOT NULL,
    ts TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- HNSW index for pgvector embeddings per pgvector docs
CREATE INDEX IF NOT EXISTS issue_vectors_embedding_hnsw ON issue_vectors
USING hnsw (embedding vector_l2_ops)
WITH (m = 16, ef_construction = 200);

-- Optional IVF index for hybrid workloads
CREATE INDEX IF NOT EXISTS issue_vectors_embedding_ivfflat ON issue_vectors
USING ivfflat (embedding vector_l2_ops)
WITH (lists = 100);

CREATE INDEX IF NOT EXISTS issues_search_vector_idx ON issues USING GIN (search_vector);
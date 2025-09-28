# RAG Issue Triage Copilot

This repository demos a Retrieval-Augmented Generation (RAG) copilot that triages GitHub and Jira issues. The implementation mirrors the ingestion, retrieval, webhook, and evaluation patterns from:
- [GitHub Issues RAG cookbook](https://huggingface.co/blog/github-issues-rag) for ingest → embed → retrive pipelines.
- [pgvector similarity search guides](https://www.tigergraph.com/blog/build-rag-applications-with-postgres-pgvector/) for HNSW/IVF index configuration and hybrid SQL retrieval.
- [GitHub webhook validation and write-back docs](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries) and [issues API examples](https://docs.github.com/en/rest/issues/issues) for webhook signature checks and label/comment actions
- [Jira cloud REST API and webhooks](https://developer.atlassian.com/cloud/jira/platform/rest/v3/) for comment, transition, and webhook handling.
- Duplicate detection research such as [Bug Deduplication via Topic Clustering (arXiv:2007.12924)](https://arxiv.org/abs/2007.12924) and [Semantic retrieval evaluation (Semantic Scholar)](https://www.semanticscholar.org/paper/Deep-learning-for-duplicate-bug-report-detection-Chen-sun/4f5b57f4b3d6d0dfd81ab41135977eb79314f0b8) to shape the offline metrics script.

## Architecture

```
/api              FastAPI application, services, and webhook routers
/worker           Redis queue worker for embeddings and similar issues
/web              React + Vite dashboard (queue, detail, search)
/db               Postgres schema with pgvector indexes
/eval             Offline duplicate detection evaluation script
/ops              Docker Compose and runtime Dockerfiles
```

### API Highlights

- `POST /webhooks/github` validates `x-Hub-Signature-256`, stores raw payloads, normalizes events, and enqueues embedding jobs.
- `POST /webhooks/jira` verifies webhook identifiers, persists issues, and queues embeddings.
- `GET /search` performs vector or hybrid retrieval with `SELECT ... ORDER BY embedding <-> $1 LIMIT K` per pgvector guidance.
- `POST /triage/propose` builds proposals using retrieved neighbors and a pluggable reranker interface.
- `POST /triage/approve` applies labels/comments/assignees to GitHub or Jira issues via official REST endpoints.

### Worker
The Redis worker consumes `triage:embed` jobs, computes SentenceTransformer embeddings, upserts them into `issue_vectors`, and refreshes the `similar` table for quick neighbor lookups.

### Evaluation

`python eval/duplicates_eval.py sample.csv` computes duplicate hit-rate, Precision@K, and NDCG using semantic similarity matrices with optional reranking hooks.

## Database

The schema enables pgvector similarity search and text search:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE issues (
  id SERIAL PRIMARY KEY,
  ...
);
CREATE TABLE issue_vectors (
  ON issue_vectors USING hnsw (embedding vector_12_ops)
  WITH (m = 16, ef_construction = 200);
CREATE INDEX IF NOT EXISTS issue_vectors_embedding_ivfflat
  ON issue_vectors USING ivfflat (embedding vector_12_ops)
  WITH (lists = 100);
);
```

See `db/init.sql` for the full schema. This includes the generated text search vector that powers hybrid retrieval.

## Running Locally

1. Copy `.env.example` to `.env` and set secrets (`GITHUB_WEBHOOK_SECRET`, `GITHUB_TOKEN`, `JIRA_*`).
2. Launch the stack:
   ```bash
   cd ops
   docker compose up --build
   ```

   Services:
   - `api`: FastAPI server on http://localhost:8000
   - `worker`: Redis consumer that populates embeddings
   - `web`: React dashboard on http://localhost:5173
   - `postgres`, `redis`: backing services
  
3. Seed historical issues by enqueuing jobs:
   ```bash
   docker compose exec api python -c "from api.services import ingest; print('Hook up backfill script here')"
   ```

4. Configure GitHub webhooks (Issues, Issue comments, Pull requests) pointing to `https://your-host/webhooks/github` with the shared secret from the docs. Configure Jira webhooks similarly and set the identifier header expected by `/webhooks/jira`.

5. Approve AI proposals from the dashboard, which relays labels/comments through the GitHub and Jira REST clients.

## CI/CD

The GitHub Actions workflow installs dependencies, compiles python modules, and runs an API smoke check against uvicorn to ensure the app boots under CI with Postgres + Redis services.

## Next Steps

- Implement backfill scripts for GitHub repos and Jira JQL queries following the GitHub issues RAG cookbook.
- Swap `NoOpReranker` for a cross-encoder reranker via Hugging Face Inference endpoints or on-prem models.
- Extend the React dashboard with authentication and richer triage analytics as the project evolves.

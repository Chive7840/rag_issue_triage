# RAG Issue Triage Copilot Starter

This repository provides a production-ready starter for a Retrieval-Augmented Generation (RAG) copilot that triages GitHub and Jira issues. The implementation mirrors the ingestion, retrieval, webhook, and evaluation patterns from:

- [GitHub Issues RAG cookbook](https://huggingface.co/blog/github-issues-rag) for ingest → embed → retrieve pipelines.
- [pgvector similarity search guides](https://www.tigergraph.com/blog/build-rag-applications-with-postgres-pgvector/) for HNSW/IVF index configuration and hybrid SQL retrieval.
- [GitHub webhook validation and write-back docs](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries) and [issues API examples](https://docs.github.com/en/rest/issues/issues) for webhook signature checks and label/comment actions.
- [Jira Cloud REST API and webhooks](https://developer.atlassian.com/cloud/jira/platform/rest/v3/) for comment, transition, and webhook handling.
- Duplicate detection research such as [Bug Deduplication via Topic Clustering (arXiv:2007.12924)](https://arxiv.org/abs/2007.12924) and [Semantic retrieval evaluation (Semantic Scholar)](https://www.semanticscholar.org/paper/Deep-learning-for-duplicate-bug-report-detection-Chen-Sun/4f5b57f4b3d6d0dfd81ab41135977eb79314f0b8) to shape the offline metrics script.

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

- `POST /webhooks/github` validates `X-Hub-Signature-256`, stores raw payloads, normalizes events, and enqueues embedding jobs.
- `POST /webhooks/jira` verifies webhook identifiers, persists issues, and queues embeddings.
- `GET /search` performs vector or hybrid retrieval with `SELECT ... ORDER BY embedding <-> $1 LIMIT K` per pgvector guidance.
- `POST /triage/propose` builds proposals using retrieved neighbors and a pluggable reranker interface.
- `POST /triage/approve` applies labels/comments/assignees to GitHub or Jira issues via official REST endpoints.

### Worker

The Redis worker consumes `triage:embed` jobs, computes SentenceTransformer embeddings, upserts them into `issue_vectors`, and refreshes the `similar` table for quick neighbor lookups.

### Evaluation

`python eval/duplicates_eval.py sample.csv` computes duplicate hit-rate, Precision@K, and NDCG using semantic similarity matrices with optional reranking hooks, aligning with duplicate detection literature.

## Database

The schema enables pgvector similarity search and text search:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE issues (
                       id SERIAL PRIMARY KEY,
   ...
);
CREATE TABLE issue_vectors (
                              issue_id INT REFERENCES issues(id) ON DELETE CASCADE,
                              embedding VECTOR(768),
   ...
);
CREATE INDEX IF NOT EXISTS issue_vectors_embedding_hnsw
   ON issue_vectors USING hnsw (embedding vector_l2_ops)
   WITH (m = 16, ef_construction = 200);
CREATE INDEX IF NOT EXISTS issue_vectors_embedding_ivfflat
   ON issue_vectors USING ivfflat (embedding vector_l2_ops)
   WITH (lists = 100);
```

See `db/init.sql` for the full schema, including the generated text search vector that powers hybrid retrieval.

## Running Locally

1. Copy `.env.example` to `.env` and set secrets (`GITHUB_WEBHOOK_SECRET`, `GITHUB_TOKEN`, `JIRA_*`).
   - If you plan to expose the stack through Cloudflare, create a Zero Trust tunnel connector (select **Docker** as the installation method) and copy the token into `CLOUDFLARE_TUNNEL_TOKEN`. Leave the variable unset if you do not need an HTTPS tunnel.
2. Enable Docker BuildKit so the pip cache mount in the Dockerfiles is active (BuildKit is on by default for recent Docker versions; otherwise export the variable before building):

   ```bash
   export DOCKER_BUILDKIT=1
   ```

   Launch the stack:

   ```bash
   cd ops
   docker compose up --build
   ```

   Services:
   - `api`: FastAPI server on http://localhost:8000
   - `worker`: Redis consumer that populates embeddings
   - `web`: React dashboard on http://localhost:5173
   - `postgres`, `redis`: backing services

   The first build downloads Python dependencies once and reuses them through the BuildKit cache (`--mount=type=cache`), so subsequent `docker compose up --build` runs that do not touch `requirements.txt` skip lengthy reinstall steps. To start the optional Cloudflare tunnel once `CLOUDFLARE_TUNNEL_TOKEN` is configured, include the profile:

   ```bash
   docker compose --profile cloudflared up --build
   ```

   This brings up the standard services plus a `cloudflared` sidecar that publishes HTTPS endpoints for the webhook routes.

3. When the tunnel profile is active, inspect the logs to discover your public hostname:

   ```bash
   docker compose logs -f cloudflared
   ```

   The output includes the `https://<random>.trycloudflare.com` URL assigned to your tunnel.

4. Seed historical issues by enqueueing jobs:

   ```bash
   docker compose exec api python -c "from api.services import ingest; print('Hook up backfill script here')"
   ```

   (Adapt this command to call a GitHub/Jira fetcher per the referenced cookbook.)

5. Configure GitHub webhooks (Issues, Issue comments, Pull requests) pointing to `https://<your-tunnel-hostname>/webhooks/github` with the shared secret from the docs. Configure Jira webhooks to `https://<your-tunnel-hostname>/webhooks/jira` and include the identifier header expected by `/webhooks/jira`.

6. Approve AI proposals from the dashboard, which relays labels/comments through the GitHub and Jira REST clients.

## CI/CD

The GitHub Actions workflow installs dependencies, compiles Python modules, and runs an API smoke check against uvicorn to ensure the app boots under CI with Postgres + Redis services.

## Next Steps

- Implement backfill scripts for GitHub repos and Jira JQL queries following the GitHub issues RAG cookbook.
- Swap `NoOpReranker` for a cross-encoder reranker via Hugging Face Inference endpoints or on-prem models.
- Extend the React dashboard with authentication and richer triage analytics as you evolve beyond this starter.
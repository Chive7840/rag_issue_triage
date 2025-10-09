# RAG Issue Triage Copilot Starter

This a Retrieval-Augmented Generation (RAG) copilot that triages GitHub and Jira issues. The implementation mirrors the ingestion, retrieval, webhook, and evaluation patterns from:

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

### Resetting the sandbox

Use the helper script under `ops/scripts` whenever you need to clear a 
service's containers, images, or persistent data. This is especially handy if 
schema changes make the existing Postgres volume incompatible with the latest
bootstrapping logic.

```bash
# Drop the Postgres container and remove its pgdata volume
python ops/scripts/reset_sandbox.py --services postgres
```

# Reset every service and prune the built images so the next `docker compose up`
# performs clean rebuilds
python ops/scripts/reset_sandbox.py --all --prune-images

# Keep the postgres volume but remove the API/worker images
python ops/scripts/reset_sandbox.py --services api worker --prune-images --keep-volume

Provide `--project-name` if you run Compose with a custom project Label; the 
script otherwise auto-detects the sandbox project name from the Compose
configuration.

## CI/CD

The GitHub Actions workflow installs dependencies, compiles Python modules, and runs an API smoke check against uvicorn to ensure the app boots under CI with Postgres + Redis services.

## Next Steps

- Implement backfill scripts for GitHub repos and Jira JQL queries following the GitHub issues RAG cookbook.
- Swap `NoOpReranker` for a cross-encoder reranker via Hugging Face Inference endpoints or on-prem models.
- Extend the React dashboard with authentication and richer triage analytics as you evolve beyond this starter.

## Portfolio Sandbox Blueprint

Add functionality to Sandbox the program without live data from GitHub or Jira -> see the [containerized portfolio sandbox plan](docs/containerized_sandbox_plan.md). The blueprint covers:

- A Docker Compose topology that mirrors production services while remaining self-contained.
- Modern base images and dependency management approaches that avoid deprecated runtimes.
- Synthetic GitHub and Jira datasets with deterministic seeding for repeatable demos.
- Automation for database initialization, embedding warm-up, and observability.
- Portfolio polish, including walkthrough assets and reset scripts.

### Synthetic Data Strategy

The deterministic issue generator under `api/services/generate_deterministic_sample.py` now supports Local paraphrasing
so that synthetic records better reflect natural variations. The variations will not violate Lockable entities such as
repo names, timestamps, or code blocks.

- **Providers**
  - `rule` (default): Lightweight synonym swaps, passive/active voice flips, and filler removal constrained by an edit budget.
  - `hf_local`: optional Hugging Face `text2text-generation` pipeline that loads from an on-disk cache and stays offline at
    runtime. Downloads are disabled unless explicitly permitted.
- **Locked entities** – Repo/project identifiers, URLs, file paths, timestamps, versions, inline/fenced code, and stack traces
  are masked before any provider runs to guarantee identical restoration afterwards.
- **Budgets** – Set `--paraphrase-budget` (default 15 tokens) and the provider respects a 25% edit ceiling per section.
- **Caching & offline requirement** – `hf_local` reads the model from `HF_CACHE_DIR` (defaults to `.cache/hf`). If the cache is
  empty and downloads are disabled, the CLI raises a clear error so you can prime the cache ahead of time.
- **CLI flags**
   - `--paraphrase {off|rule|hf_local}` to select the provider.
   - `--hf-model`, `--hf-cache`, `--hf-device`, and `--hf-allow-downloads` for Hugging Face overrides.
   - `--seed` governs deterministic edits for both providers.

Example commands:

```bash
# rule-based paraphrasing
python -m api.services.generate_deterministic_sample --flavor github --count 200 --paraphrase rule

# hf_local using cached t5-small on GPU 0 (downloads allowed only for the priming run)
PARAPHRASE_MODEL=t5-small HF_CACHE_DIR=.cache/hf HF_DEVICE=cuda:0 \
python -m api.services.generate_deterministic_sample --flavor jira --count 100 --paraphrase hf_local --hf-device cuda:0 --hf-allow-downloads
```
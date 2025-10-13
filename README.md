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

### Origin-safe issue viewer quickstart

After rebuilding the container images you need to rebuild the web bundle and
restart the API so the origin-safe viewer plugin mounts correctly.

1. Install the Python application dependencies (editable installs now work out
   of the box):

   ```bash
   pip install -e .[test]
   ```

2. Ensure the sandbox dataset is present. The API automatically performs this
   step on startup, but you can run the bootstrap script manually if you are
   unsure whether the database was seeded:

   ```bash
   python -m api.sandbox.bootstrap
   ```

3. Start the API (adjust the bind address as needed for Docker or VS Code
   tunnels):

   ```bash
   uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. Reinstall web dependencies and rebuild the bundle so `app/register-plugins.ts`
   is compiled alongside the existing dashboard:

   ```bash
   cd web
   npm install
   npm run build   # or npm run dev for the Vite dev server
   ```

5. Visit any canonical route such as
   `http://localhost:5173/gh/rag-sandbox/sample-repo/issues/1`. The viewer will
   hide the host dashboard only for `/gh/...` and `/jira/...` routes and will
   render the deterministic banner, disabled origin button, and sanitized body
   content.

6. Run the acceptance tests that cover the API endpoints and the link rewriting
   behaviour:

   ```bash
   pytest tests/http/test_viewer_api.py tests/services/test_origin_safe_rendering.py
   ```

These steps guarantee that the plugin is registered, the sandbox data is
available, and the front-end bundle includes the origin-safe routes after a
fresh container build.


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
- Bundled synthetic GitHub and Jira datasets checked into the repo for repeatable demos.
- Automation for database initialization, embedding warm-up, and observability.
- Portfolio polish, including walkthrough assets and reset scripts.

### Synthetic Data Strategy

Synthetic GitHub and Jira archives live under `db/sandbox` inside the repository.
They are generated offline and checked in so the sandbox boots instantly without
any deterministic CLI tooling. The paraphrasing pipeline relies on Hugging Face's
`t5-small` inference API to keep the language varied while respecting sensitive
entities.

- **Provider** – `hf_api` (default) invokes the hosted Hugging Face inference API.
  Provide `HUGGINGFACE_API_TOKEN` when authenticated access is required; otherwise
  the client falls back to the public endpoint limits.
- **Locked entities** – Repo/project identifiers, URLs, file paths, timestamps,
  versions, inline/fenced code, and stack traces are masked before any API call so
  they are restored verbatim afterwards.
- **Budgets** – `paraphrase_budget` still defaults to 15 tokens with a 25% edit
  ceiling per section to avoid excessive rewrites.
- **Updating data** – Refresh the NDJSON archives manually when new demo scenarios
  are required, then commit them alongside documentation changes.


TODO Item: Build in dynamic label suggestions during approval flow based on semantic matches to the issue corpus.
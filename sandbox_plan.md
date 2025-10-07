# Containerized Portfolio Sandbox Plan

This document captures the state of the sandbox after completing implementation phases 1–4. The sandbox boots a self-contained copy of the RAG Issue Triage stack with deterministic, synthetic GitHub and Jira data so reviewers can explore ingestion, retrieval, and triage flows without connecting to external services.

## 1. Goals

- **Zero external dependencies**: Visitors can launch the sandbox without connecting to real GitHub or Jira tenants.
- **Deterministic experience**: Every run seeds identical data and embeddings so the UI and API behave predictably during demos.
- **Production-parity architecture**: Containers mirror the real deployment topology (API, worker, Postgres, Redis, web client) to highlight engineering depth.
- **Fast launch time**: Images leverage multi-stage builds and cached dependencies to minimize cold-start delays on portfolio platforms (e.g., GitHub Codespaces, Render).
- **Observability baked in**: Logs and metrics are preconfigured to help reviewers understand system behavior quickly.

## 2. Target Topology

Docker Compose orchestrates the sandbox with modern, non-deprecated base images:

| Service          | Purpose                           | Base image                           | Notes |
|------------------|-----------------------------------|---------------------------------------|-------|
| `api`            | FastAPI application               | `python:3.12-slim`                    | Installs dependencies with `uv` during the build and runs under `uvicorn`. |
| `worker`         | Background embedding jobs         | `python:3.12-slim`                    | Copies the prebuilt Python environment produced for the API image. |
| `web`            | React + Vite dashboard            | `node:20-alpine` / `caddy:2-alpine`   | Builds static assets with `pnpm` and serves them through Caddy. |
| `postgres`       | Metadata + pgvector store         | `postgres:16`                         | Loads schema from `db/init.sql` via `/docker-entrypoint-initdb.d/`. |
| `redis`          | Job queue                         | `redis:7-alpine`                      | Default configuration is sufficient for the demo. |
| `otel-collector` | Optional metrics/trace fan-out    | `otel/opentelemetry-collector:0.94.0` | Streams traces to the console exporter for visibility. |
| `cloudflared`    | Optional HTTPS tunnel             | `cloudflare/cloudflared:2024.2.1`     | Enabled via a Compose profile for remote demos. |

## 3. Build Strategy

1. **Consolidated Python dependencies**
   - `pyproject.toml` + `uv.lock` pin runtime and test requirements for Python 3.12.
   - `ops/containers/api.Dockerfile` performs an `uv export` and installs once in a build stage that both runtime containers reuse.

2. **Node build caching**
   - `ops/containers/web.Dockerfile` enables Corepack, activates `pnpm@9.15.2`, and uses `pnpm fetch` + `pnpm install --offline` for reproducible builds.
   - The final stage serves `/app/dist` through `caddy`, matching the production deployment model.

3. **Database initialization**
   - `db/init.sql` provisions `issues`, `issue_vectors`, `labels`, and `similar` tables with pgvector indexes.
   - Compose mounts the SQL script automatically; seeding now happens through an explicit command (see §5).

4. **Vector index warm-up**
   - Synthetic GitHub/Jira NDJSON archives are built into the API image (`db/synth_data/*.ndjson.gz`).
   - Loading these files triggers embedding jobs via Redis so the worker can upsert vectors idempotently.

5. **Environment configuration**
   - `.env.sandbox` captures non-sensitive defaults for Postgres, Redis, and optional Cloudflare tunneling.
   - `ops/docker-compose.yaml` loads the environment file so credentials stay out of image layers.

## 4. Synthetic Data Strategy

The sandbox ships deterministic GitHub and Jira payloads that mirror common workflows:

### 4.1 GitHub-like dataset

- `api/services/generate_deterministic_sample.py` generates reproducible payloads without third-party packages.
- The API Dockerfile invokes the generator during build time, emitting `db/synth_data/github_issues.ndjson.gz` with 750 issues, comments, labels, and repository metadata.
- The dataset purposefully duplicates a subset of descriptions so the UI can demonstrate duplicate detection.

### 4.2 Jira-like dataset

- The same generator supports a `jira` flavor that exports `db/synth_data/jira_issues.ndjson.gz` following To Do → In Progress → Done workflows.
- Jira payloads include transitions, project keys, assignees, and comments so UI cards can distinguish sources.

### 4.3 Consistency and reproducibility

- All runs use the seeded `demo-42` configuration to keep JSON outputs identical across builds.
- `tests/services/test_ingest.py` validates the normalization logic that loads these payloads, preventing schema drift.
- Longer-form documentation for data knobs and prompts will land in `docs/` during phase 5 polish.

## 5. Developer & Reviewer Workflow

1. **Clone and bootstrap**
   ```bash
   cp .env.sandbox .env
   cd ops
   docker compose -f docker-compose.sandbox.yml up --build
   ```

2. **Database and queue startup**
   - `postgres` automatically applies `db/init.sql`, creating pgvector indexes and helper tables.
   - `worker` connects to Redis and blocks on the `triage:embed` queue.

3. **Load synthetic issues**
   - The API container already includes `db/synth_data/github_issues.ndjson.gz` and `db/synth_data/jira_issues.ndjson.gz`.
   - Run the documented Python helper that iterates through each archive, calls `api.services.ingest.normalize_*`, `store_issue`, and `enqueue_embedding_job` to queue embeddings until the Phase 5 CLI lands.

4. **UI access**
   - The dashboard is exposed at `http://localhost:4173` by the Caddy container.
   - Login-free access remains; polishing the landing page badge is part of phase 5.

5. **Observability**
   - Structured logging via `api.utils.logging_utils` is enabled by default.
   - Optional Cloudflare tunneling runs behind the `cloudflared` profile for remote demos.

6. **Reset workflow (manual today)**
   - Run `docker compose -f ops/docker-compose.sandbox.yml down --volumes` when you need a clean slate. This drops the active `pgdata16` volume so Postgres re-initializes with version 16–compatible files.
   - If you booted the sandbox prior to the Postgres 16 upgrade, remove the legacy volume once via `docker volume rm rag_issue_triage_pgdata` so it does not linger as dead weight.
   - A dedicated reset script will be added during the documentation/polish phase.

## 6. Portfolio Presentation Enhancements

- Add a walkthrough notebook (`docs/sandbox_walkthrough.ipynb`) that demonstrates:
   1. Querying similar issues via the API.
   2. Approving AI triage proposals and observing comment/label updates in the synthetic payloads.
   3. Inspecting embeddings using UMAP visualizations.
- Embed short Loom-style GIFs or screenshots of the dashboard into the README to showcase the experience.
- Highlight the architecture by including a Mermaid diagram illustrating service interactions within the Compose stack.

## 7. Implementation Phases

1. **Phase 1 – Preparation ✅**
   - Locked dependencies in `pyproject.toml`/`uv.lock` and aligned runtimes on Python 3.12.
   - Added targeted tests (e.g., ingestion normalization) so data contracts stay stable.

2. **Phase 2 – Container build refactor ✅**
   - Introduced multi-stage Dockerfiles in `ops/containers/` and updated `ops/docker-compose.yaml` plus `.env.sandbox`.
   - Added an optional `cloudflared` profile for remote demos without altering the core stack.

3. **Phase 3 – Data generation tooling ✅**
   - Implemented `api/services/generate_deterministic_sample.py` and built GitHub/Jira NDJSON archives during image builds.
   - Ensured outputs remain reproducible through seeded generators.

4. **Phase 4 – Seeding & bootstrap automation ✅**
   - Wired ingestion helpers and the Redis worker so loading NDJSON data enqueues embeddings automatically.
   - Documented the temporary inline loader workflow; extracting a CLI lands in phase 5.

5. **Phase 5 – Documentation & polish (next)**
   - Expand README/docs with walkthrough notebooks, reset scripts, and reviewer checklists.
   - Capture screenshots/GIFs highlighting the sandbox UI once the polish work lands.

## 8. Future Enhancements

- Integrate a lightweight authentication layer (Magic Links via Clerk or Supabase) if you need to gate the demo.
- Package the sandbox as a `devcontainer.json` so visitors can launch it with one click in GitHub Codespaces.
- Add a GitHub Actions workflow that builds and pushes the sandbox images to GHCR, enabling quick redeploys on platforms like Railway or Fly.io.
- Explore streaming model inference (e.g., `gpt-4o-mini`) once API costs are acceptable; keep the sandbox on open-source models (`sentence-transformers/all-MiniLM-L12-v2`) to avoid external dependencies.
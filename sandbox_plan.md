# Containerized Portfolio Sandbox Plan

This document outlines the steps required to transform the RAG Issue Triage project into a self-contained sandbox. 
The objective is to provide a reproducible environment that showcases ingestion, retrieval, and triage flows with realistic—but synthetic—GitHub and Jira data.

## 1. Goals

- **Zero external dependencies**: Visitors can launch the sandbox without connecting to real GitHub or Jira tenants.
- **Deterministic experience**: Every run seeds identical data and embeddings so the UI and API behave predictably during demos.
- **Production-parity architecture**: Containers mirror the real deployment topology (API, worker, Postgres, Redis, web client) to highlight engineering depth.
- **Fast launch time**: Images leverage multi-stage builds and cached dependencies to minimize cold-start delays on portfolio platforms (e.g., GitHub Codespaces, Render).
- **Observability baked in**: Logs and metrics are preconfigured to help reviewers understand system behavior quickly.

## 2. Target Topology

Use Docker Compose to orchestrate the sandbox. All images are built from modern, non-deprecated bases:

| Service  | Purpose                          | Base image                      | Notes |
|----------|----------------------------------|----------------------------------|-------|
| `api`    | FastAPI application              | `python:3.12-slim`               | Installs dependencies with `pip` + `uv` (PEP 668 compliant) and runs under `uvicorn`.
| `worker` | Background embedding jobs        | `python:3.12-slim`               | Shares the `api` wheel to avoid duplicate dependency resolution.
| `web`    | React + Vite dashboard           | `node:20-alpine`                 | Builds static assets in a stage, serves them through `caddy:2-alpine` for production parity.
| `postgres` | Metadata + pgvector store      | `postgres:16`                    | Initializes schema via `/docker-entrypoint-initdb.d/` scripts.
| `redis`  | Job queue                        | `redis:7-alpine`                 | Default configuration is sufficient for the demo.
| `otel-collector` | Optional metrics/trace fan-out | `otel/opentelemetry-collector:0.94.0` | Streams traces to the console exporter for visibility.

## 3. Build Strategy

1. **Consolidate Python dependencies**:
    - Add a `pyproject.toml` and lockfile (e.g., `uv lock`) to describe runtime requirements without deprecated packages.
    - Build a shared wheelhouse during the image build and copy it into both `api` and `worker` images.

2. **Node build caching**:
    - Use `corepack enable` in the Node stage and `pnpm@9` to install dependencies with frozen lockfiles.
    - Emit production assets to `/app/dist` and copy them into a lightweight web server image.

3. **Database initialization**:
    - Place SQL schema and seed scripts in `db/sandbox/`.
    - Compose mounts those scripts into Postgres so that `init.sql` and `seed.sql` run automatically.

4. **Vector index warm-up**:
    - Bundle a precomputed embeddings parquet (`db/sandbox/embeddings.parquet`) to avoid recomputation on boot.
    - Provide a management command `python -m api.sandbox.load_embeddings` that checks for existing vectors before loading.

5. **Environment configuration**:
    - Supply `.env.sandbox` with non-sensitive defaults.
    - Compose file loads the environment to keep credentials out of image layers.

## 4. Synthetic Data Strategy

Because real GitHub/Jira data is unavailable, generate realistic datasets offline and package them with the repo:

### 4.1 GitHub-like dataset

- Implement a script `ops/scripts/generate_github_sample.py` that uses `Faker` and a curated prompt library to produce:
    - Repositories with metadata (name, description, languages).
    - Issues, pull requests, comments, labels, and events.
- Save the output as JSON Lines in `db/sandbox/github_issues.jsonl`.
- During sandbox startup, run an ingestion command that:
    1. Loads the JSON Lines into the Postgres `issues` table.
    2. Calls the embedding worker synchronously to embed text fields.
- Include a handful of intentionally duplicated issue descriptions to demonstrate triage suggestions.

### 4.2 Jira-like dataset

- Create `ops/scripts/generate_jira_sample.py` using `Faker` plus canonical Jira workflows (To Do → In Progress → Done).
- Export issues to `db/sandbox/jira_issues.jsonl` with project keys, transitions, and comments.
- Provide mapping tables so the API layer can distinguish between GitHub and Jira sources when populating UI cards.

### 4.3 Consistency and reproducibility

- Seed the random number generator and keep source prompt templates under version control to ensure deterministic output.
- Document the data generation process in `docs/sandbox_data_generation.md` so reviewers can audit the synthetic content.

## 5. Developer & Reviewer Workflow

1. **Clone and bootstrap**:
   ```bash
   cp .env.sandbox .env
   docker compose -f ops/docker-compose.sandbox.yml up --build
   ```

2. **Automatic seeding**:
    - `postgres` runs `init.sql` to create tables and `seed.sql` to insert GitHub/Jira issues.
    - `worker` listens for `triage:embed` jobs; the API posts the precomputed embeddings if available.

3. **UI access**:
    - Web dashboard is exposed at `http://localhost:4173` (static Caddy server).
    - Provide login-free access but annotate the landing page with a “Demo Data” badge.

4. **Observability**:
    - `otel-collector` exports logs/traces to stdout; developers can toggle it via Compose profiles.
    - Include Grafana dashboards as JSON exports if deeper metrics are desired in the future.

5. **Reset button**:
    - Ship a management script `ops/scripts/reset_sandbox.sh` that drops and recreates the database plus embeddings so reviewers can restore the initial state quickly.

## 6. Portfolio Presentation Enhancements

- Add a walkthrough notebook (`docs/sandbox_walkthrough.ipynb`) that demonstrates:
    1. Querying similar issues via the API.
    2. Approving AI triage proposals and observing comment/label updates in the synthetic payloads.
    3. Inspecting embeddings using UMAP visualizations.
- Embed short Loom-style GIFs or screenshots of the dashboard into the README to showcase the experience.
- Highlight the architecture by including a Mermaid diagram illustrating service interactions within the Compose stack.

## 7. Implementation Phases

1. **Preparation**
    - Audit current dependencies and update them to the latest minor/patch releases.
    - Introduce `pyproject.toml` / lockfiles and ensure CI uses them.

2. **Container build refactor**
    - Create new Dockerfiles under `ops/containers/` with multi-stage builds as described above.
    - Update Compose configuration to reference the new images and environment files.

3. **Data generation tooling**
    - Build the synthetic data scripts and commit the generated datasets.
    - Add tests that assert dataset schemas so future edits remain compatible.

4. **Seeding & bootstrap automation**
    - Implement management commands to load sample data and embeddings during startup.
    - Extend CI to run `docker compose -f ops/docker-compose.sandbox.yml config` ensuring the sandbox definition stays valid.

5. **Documentation & polish**
    - Update README with sandbox instructions, screenshots, and links to walkthrough materials.
    - Provide a checklist for reviewers (e.g., "Open issue #12, approve suggestion, observe comment").

## 8. Future Enhancements

- Integrate a lightweight authentication layer (Magic Links via Clerk or Supabase) if you need to gate the demo.
- Package the sandbox as a `devcontainer.json` so visitors can launch it with one click in GitHub Codespaces.
- Add a GitHub Actions workflow that builds and pushes the sandbox images to GHCR, enabling quick redeploys on platforms like Railway or Fly.io.
- Explore streaming model inference (e.g., `gpt-4o-mini`) once API costs are acceptable; keep the sandbox on open-source models (`sentence-transformers/all-MiniLM-L12-v2`) to avoid external dependencies.

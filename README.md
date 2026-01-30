# RAG Issue Triage Copilot

A **data + automation pipeline** that uses retrieval-augmented techniques to triage, classify, and act on large volumes of GitHub and Jira issue text.

This project demonstrates how **AI-assisted text analysis** can be applied to real operational workflows—reducing manual review while remaining transparent, repeatable, and human-approved.

---

## Problem → Solution → Outcome

### Problem
Teams handling GitHub or Jira issues often spend significant time manually:
- Reading and classifying incoming issues
- Identifying duplicates or related reports
- Applying labels, comments, or workflow transitions

This process is slow, inconsistent, and difficult to scale as issue volume grows.

### Solution
This project implements an **automated issue-triage pipeline** that:
- Ingests GitHub and Jira issues via webhooks
- Embeds and retrieves similar historical issues
- Proposes labels, comments, and assignments using retrieved context
- Requires explicit human approval before writing back to external systems
- Runs continuously via CI/CD with Postgres and Redis backing services

### Outcome
- Reduced manual triage effort
- More consistent issue categorization
- Automated handling of new incoming data
- A reusable pattern for other text-heavy workflows (support tickets, feedback, logs)

---

## What This Project Demonstrates

- AI-assisted text processing applied to operational data
- End-to-end data pipelines (ingest → embed → retrieve → act)
- Automation that replaces recurring manual review
- Production-style structure with CI/CD, background workers, and persistence

This is intentionally a **starter / sandbox implementation**, not a research prototype.

---

## Architecture

```
/api              FastAPI application, services, and webhook routers
/worker           Redis queue worker for embeddings and similar issues
/web              React + Vite dashboard (queue, detail, search)
/db               Postgres schema with pgvector indexes
/eval             Offline duplicate detection evaluation script
/ops              Docker Compose and runtime Dockerfiles
```

---

## Implementation References

The implementation mirrors established public guidance and research:

- GitHub Issues RAG cookbook – https://huggingface.co/blog/github-issues-rag
- pgvector similarity search guides – https://www.tigergraph.com/blog/build-rag-applications-with-postgres-pgvector/
- GitHub webhook validation and write-back docs – https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
- GitHub Issues API examples – https://docs.github.com/en/rest/issues/issues
- Jira Cloud REST API and webhooks – https://developer.atlassian.com/cloud/jira/platform/rest/v3/
- Duplicate detection research:
  - https://arxiv.org/abs/2007.12924
  - https://www.semanticscholar.org/paper/Deep-learning-for-duplicate-bug-report-detection-Chen-Sun/4f5b57f4b3d6d0dfd81ab41135977eb79314f0b8

---

## API Highlights

- `POST /webhooks/github`  
  Validates `X-Hub-Signature-256`, stores raw payloads, normalizes events, and enqueues embedding jobs.

- `POST /webhooks/jira`  
  Verifies webhook identifiers, persists issues, and queues embeddings.

- `GET /search`  
  Performs vector or hybrid retrieval using pgvector (`embedding <-> query`).

- `POST /triage/propose`  
  Builds triage proposals using retrieved neighbors and a pluggable reranker interface.

- `POST /triage/approve`  
  Applies labels, comments, and assignees to GitHub or Jira issues via official REST APIs.

---

## Worker

The Redis worker consumes `triage:embed` jobs, computes SentenceTransformer embeddings, upserts them into `issue_vectors`, and refreshes the `similar` table for fast neighbor lookups.

---

## Evaluation

Running:

```
python eval/duplicates_eval.py sample.csv
```

Computes duplicate hit-rate, Precision@K, and NDCG using semantic similarity matrices with optional reranking hooks.

---

## Database

The schema enables pgvector similarity search and hybrid text search:

```
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
```

See `db/init.sql` for the full schema.

---

## CI/CD

The GitHub Actions workflow installs dependencies, builds the services, and runs an API smoke test against Postgres and Redis to ensure the application boots correctly under CI.

---

## Why This Matters as a Portfolio Project

This repository focuses on:
- Turning unstructured text into actionable workflows
- Using AI tools to reduce operational overhead
- Building systems that are testable, repeatable, and deployable

---

## Next Steps

- Implement historical backfill for GitHub repos and Jira JQL queries
- Replace the no-op reranker with a cross-encoder
- Extend the dashboard with authentication and analytics

---

## TODO

- Add dynamic label suggestions during approval based on semantic matches

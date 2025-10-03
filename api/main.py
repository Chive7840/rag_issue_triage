"""FastAPI application wiring the ingestion, retrieval, and triage flows."""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from redis import asyncio as aioredis

from .clients.github import GitHubClient
from .clients.jira import JiraClient
from .schemas import ProposalApproval, SearchResponse, TriageProposal, TriageRequest
from .services import embeddings, retrieve, rerank, triage
from .webhooks import github as github_webhooks
from .webhooks import jira as jira_webhooks
from api.utils.logging_utils import get_logger, logging_context, setup_logging

setup_logging()
logger = get_logger("api.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    with logging_context(component="api", event="startup"):
        logger.info("Initializing API dependencies")
    db_pool = await asyncpg.create_pool(dsn=database_url)
    redis = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)

    app.state.db_pool = db_pool
    app.state.redis = redis
    app.state.cloudflare_tunnel_token = os.getenv("CLOUDFLARE_TUNNEL_TOKEN", "")
    app.state.github_webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    app.state.jira_webhook_secret = os.getenv("JIRA_WEBHOOK_SECRET", "")
    app.state.github_token = os.getenv("GITHUB_TOKEN", "")
    app.state.jira_base_url = os.getenv("JIRA_BASE_URL", "")
    app.state.jira_email = os.getenv("JIRA_EMAIL", "")
    app.state.jira_token = os.getenv("JIRA_API_TOKEN", "")
    app.state.json_loads = json.loads

    try:
        yield
    finally:
        with logging_context(component="api", event="shutdown"):
            logger.info("Shutting down API dependencies")
        await app.state.db_pool.close()
        await app.state.redis.close()


app = FastAPI(title="RAG issue Triage Copilot", lifespan=lifespan)
app.include_router(github_webhooks.router)
app.include_router(jira_webhooks.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_db_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool


@app.get("/healthz")
async def healthcheck(request: Request) -> dict[str, Any]:
    pool: asyncpg.Pool = request.app.stater.db_pool
    async with pool.acquire() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/search", response_model=SearchResponse)
async def search(
        q: str = Query(..., min_length=2),
        k: int = Query(10, ge=1, le=50),
        hybrid_mode: bool = Query(False, alias="hybrid"),
        alpha: float = Query(0.5, ge=0.0, le=1.0),
        pool: asyncpg.Pool = Depends(get_db_pool),
) -> SearchResponse:
    with logging_context(route="/search", query=q, hybrid=hybrid_mode, limit=k):
        logger.info("Processing search request")
        embedding = embeddings.encode_texts([q])[0]
        if hybrid_mode:
            results = await retrieve.hybrid_search(pool, embedding, q, limit=k, alpha=alpha)
        else:
            results = await retrieve.vector_search(pool, embedding, limit=k)
        logger.info("Search completed", extra={"context": {"result_count": len(results)}})
        return SearchResponse(query=q, results=results)


@app.post("/triage/propose", response_model=TriageProposal)
async def propose_triage(
        payload: TriageRequest,
        pool: asyncpg.Pool = Depends(get_db_pool),
) -> TriageProposal:
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            "SELECT title, body FROM issues WHERE id = $1",
            payload.issue_id,
        )
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="issue not found")
        vector_record = await conn.fetchrow(
            """
            SELECT embedding, model
            FROM issue_vectors
            WHERE issue_id = $1
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            payload.issue_id,
        )
    if vector_record:
        embedding = np.array(vector_record["embedding"], dtype=np.float32)
        model_name = vector_record["model"]
    else:
        embedding = embeddings.embedding_for_issue(record["title"], record["body"])
        model_name = embeddings.DEFAULT_MODEL
    with logging_context(route="/triage/propose", issue_id=payload.issue_id):
        logger.info("Generating triage proposal")
        proposal = await triage.propose(
            pool,
            payload.issue_id,
            embedding,
            rerank.NoOpReranker(),
            model_name=model_name,
        )
        logger.info("Proposal generated")
        return proposal


@app.post("/triage/approve")
async def approve_triage(
        payload: ProposalApproval,
        pool: asyncpg.Pool = Depends(get_db_pool)
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            "SELECT source, repo, project, external_key, raw_json FROM issues WHERE id = $1",
            payload.issue_id,
        )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="issue not found")
    raw = record["raw_json"] or {}
    if payload.source == "github" and record["source"] == "github":
        repo = record["repo"]
        number = raw.get("issue", {}).get("number") or raw.get("number")
        if not (repo and number):
            raise HTTPException(status_code=400, detail="missing repo or number")
        client = GitHubClient(token=app.state.github_token)
        try:
            with logging_context(route="/triage/approve", source="github", repo=repo, number=number):
                logger.info("Applying GitHub triage actions")
                if payload.labels:
                    await client.add_labels(repo, number, payload.labels)
                if payload.assignee:
                    await client.assign_issue(repo, number, [payload.assignee])
                if payload.comment:
                    await client.create_comment(repo, number, payload.comment)
        finally:
            await client.close()
    elif payload.source == "jira" and record["source"] == "jira":
        base_url = app.state.jira_base_url
        if not base_url:
            raise HTTPException(status_code=400, detail="jira base url missing")
        client = JiraClient(base_url=base_url, email=app.state.jira_email, api_token=app.state.jira_token)
        key = raw.get("issue", {}).get("key") or raw.get("key")
        if not key:
            raise HTTPException(status_code=400, detail="missing jira key")
        try:
            with logging_context(route="/triage/approve", source="jira", issue_key=key):
                logger.info("Applying Jira triage actions")
                if payload.assignee:
                    await client.assign(key, payload.assignee)
                if payload.comment:
                    await client.add_comment(key, payload.commit)
        finally:
            await client.close()
    else:
        raise HTTPException(status_code=400, detail="source mismatch")
    return {"ok": True}

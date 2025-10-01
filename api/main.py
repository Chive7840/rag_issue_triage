"""FastAPI application wiring the ingestion, retrieval, and triage flows."""
from __future__ import annotations

import json

import os
from typing import Any

import asyncpg
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from redis import asyncio as aioredis

from .clients.github import GitHubClient
from .clients.jira import JiraClient

from logging_utils import get_logger

def bootstrap_api_logging() -> None:
    """Initialize logging during API startup."""

    setup_logging()
    logger = get_logger("api.bootstrap")
    logger.info("API logging configured", extra={"context": {"component": "api"}})

@asynccontextmanager
async def lifespan(app: FastAPI) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error(f"Error type: {RuntimeError}")
        raise RuntimeError("DATABASE_URL is required")
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    app.include_router()    # placeholder for github_webhooks
    app.include_router()    # placeholder for jira_webhooks
    app.state.db_pool = await asyncpg.create_pool(dsn=database_url)
    app.state.redis = aioredis.from_url(redis_url, encoding="utf-8", decode_response=True)
    app.state.github_webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    app.state.jira_webhook_secret = os.getenv("JIRA_WEBHOOK_SECRET", "")
    app.state.github_token = os.getenv("GITHUB_TOKEN", "")
    app.state.jira_base_url = os.getenv("JIRA_BASE_URL", "")
    app.state.jira_email = os.getenv("JIRA_EMAIL", "")
    app.state.jira_token = os.getenv("JIRA_API_TOKEN", "")
    app.state.json_loads = json.loads

    yield
    await app.state.db_pool.close()
    await app.state.redis.close()

app = FastAPI(title="RAG issue Triage Copilot", lifespan=lifespan)

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

@app.get("search", response_model=SearchResponse)
async def search(
        q: str = Query(..., min_length=2),
        k: int = Query(10, ge=1, le=50),
        hybrid_mode: bool = Query(False, alias="hybrid"),
        alpha: float = Query(0.5, ge=0.0, le=1.0),
        pool: asyncpg.Pool = Depends(get_db_pool),
) -> SearchResponse:
    embedding = embeddings.encode_texts([q])[0]     # TODO: Remove this note once the services module is created
    if hybrid_mode:
        results = await retrieve.hybrid_search(pool, embedding, q, limit=k, alpha=alpha)
    else:
        results = await retreive.vector_search(pool, embedding, limit=k)
    return SearchResponse(query=q, results=results)

## TODO: Add the following functionality after the modules have been created:
#   - @app.post("triage/approve")

"""Redis worker that processes embedding jobs and updates Postgres."""
from __future__ import annotations

import asyncio
import json
import os

import asyncpg
import numpy as np
from redis import asyncio as aioredis

from api.services import embeddings
from api.utils.logging_utils import bind_context, clear_context, get_logger, logging_context, setup_logging

setup_logging()
logger = get_logger("worker")

async def process_job(pool: asyncpg.Pool, job: dict[str, object]) -> None:
    issue_id = int(job["issue_id"])
    force = bool(job.get("force", False))
    token = bind_context(issue_id=issue_id, force=force)
    try:
        async with pool.acquire() as conn:
            record = await conn.fetchrow("SELECT title, body FROM issues WHERE id = $1", issue_id)
            if not record:
                logger.warning("Issue not found")
                return
            if not force:
                existing = await conn.fetchrow(
                    "SELECT 1 FROM issue_vectors WHERE issue_id = $1",
                    issue_id,
                )
                if existing:
                    logger.info("Embedding already exists")
                    return
            logger.info("Computing embedding")
            vector = embeddings.embedding_for_issue(record["title"], record["body"])
            vector_list = np.asarray(vector, dtype=np.float32, copy=False).tolist()
            await conn.execute(
                """
                INSERT INTO issue_vectors (issue_id, embedding, model, updpated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (issue_id) DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    model = EXCLUDED.model,
                    updated_at = NOW()
                """,
                issue_id,
                vector_list,
                embeddings.DEFAULT_MODEL,
            )
            await conn.execute(
                """
                INSERT INTO similar (issue_id, neighbor_id, score, ts)
                SELECT $1, n.id, n.score, NOW()
                FROM (
                    SELECT i.id, 1 - (iv.embedding <-> $2) AS score
                    FROM issue_vectors iv
                    JOIN issues i ON i.id = iv.issue_id
                    WHERE iv.issue_id != $1 AND iv.model = $3
                    ORDER BY iv.embedding <-> $2
                    LIMIT 5
                ) AS n
                ON CONFLICT DO NOTHING
                """,
                issue_id,
                vector_list,
                embeddings.DEFAULT_MODEL,
            )
            logger.info("Updated embedding")
    finally:
        clear_context(token)

async def worker() -> None:
    database_url = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    pool = await asyncpg.create_pool(dsn=database_url)
    redis = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    try:
        while True:
            _, raw = await redis.blpop("triage:embed")
            job = json.loads(raw)
            try:
                with logging_context(queue="triage:embed", issue_id=job.get("issue_id")):
                    logger.info("Dequeued job")
                await process_job(pool, job)
            except Exception:   # noqa: BLE001
                with logging_context(raw_job=raw):
                    logger.exception("Failed to process job")
    finally:
        await redis.aclose()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(worker())

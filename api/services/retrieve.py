"""Retrieval service backed by Postgres + pgvector."""
from __future__ import annotations

from typing import List, Sequence

from ..schemas import RetrievalResult

import asyncpg
import numpy as np

from logging_utils import get_logger, logging_context

logger = get_logger("api.services.retrieve")


async def vector_search(
        pool: asyncpg.Pool,
        embedding: np.ndarray,
        limit: int = 10,
        model: str = "Sentence-transformers/all-MiniLM-L6-v2",
) -> Sequence[RetrievalResult]:
    vector = embedding.tolist() if hasattr(embedding, "tolist") else embedding
    with logging_context(strategy="vector", limit=limit, model=model):
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT i.id, i.title, i.repo, i.project, iv.embedding <-> $1 AS distance
                FROM issue_vectors iv
                JOIN issues i ON i.id = iv.issue_id
                WHERE iv.model = $2
                ORDER BY iv.embedding <-> $1
                LIMIT $3
                """,
                vector,
                model,
                limit,
            )
        logger.info("vector search completed", extra={"context": {"row_count": len(rows)}})
    results: List[RetrievalResult] = []
    for row in rows:
        url = None
        if row["repo"]:
            url = f"https://github.com/{row['repo']}/issues/{row['id']}"
        elif row["project"]:
            url = f"https://{row['project']}.atlassian.net/browse/{row['id']}"
        score = float(1.0 - row["distance"])
        results.append(
            RetrievalResult(
                issue_id=row["id"],
                title=row["title"],
                score=score,
                url=url,
            )
        )
    return results

async def hybrid_search(
        pool: asyncpg.Pool,
        embedding: np.ndarray,
        query: str,
        limit: int = 10,
        alpha: float = 0.5,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> Sequence[RetrievalResult]:
    vector = embedding.tolist() if hasattr(embedding, "tolist") else embedding
    with logging_context(strategy="hybrid", limit=limit, model=model, alpha=alpha):
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH vector_candidates AS (
                    SELECT iv.issue_id, 1 - (iv.embedding <-> $1) AS vector_score
                    FROM issue_vectors iv
                    WHERE iv.model = $4
                    ORDER BY iv.embedding <-> $1
                    LIMIT $2
                ),
                text_candidates AS (
                    SELECT i.id, ts_rank_cd(search_vector, plainto_tsquery('english', $3)) AS text_score
                    FROM issues i
                    WHERE search_vector @@ plainto_tsquery('english', $3)
                    ORDER BY text_score DESC
                    LIMIT $2
                )
                SELECT i.id, i.title, i.repo, i.project,
                       COALESCE(vc.vector_score, 0) AS vector_score,
                       COALESCE(tc.text_score, 0) AS text_score
                FROM issues i
                LEFT JOIN vector_candidates vc ON vc.issue_id = i.id
                LEFT JOIN text_candidates tc on tc.id = i.id
                WHERE vc.issue_id IS NOT NULL OR tc.id IS NOT NULL
                ORDER BY (COALESCE(vc.vector_score, 0) * $5 + COALESCE(tc.text_score, 0) * (1 - $5)) DESC
                LIMIT $2
                """,
                vector,
                limit,
                query,
                model,
                alpha,
            )
        logger.info("Hybrid search completed", extra={"context": {"row_count": len(rows)}})
    results: List[RetrievalResult] = []
    for row in rows:
        url = None
        if row["repo"]:
            url = f"https://github.com/{row['repo']}/issues/{row['id']}"
        elif row["project"]:
            url = f"https://{row['project']}.atlassian.net/browse/{row['id']}"
        score = float(row["vector_score"] * alpha + row["text_score"] * (1 - alpha))
        results.append(
            RetrievalResult(
                issue_id=row["id"],
                title=row["title"],
                score=score,
                url=url,
            )
        )
    return results
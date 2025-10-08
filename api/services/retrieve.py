"""Retrieval service backed by Postgres + pgvector."""
from __future__ import annotations

import json
from collections.abc import Iterable, Sequence

import asyncpg
import numpy as np

from ..schemas import RetrievalResult
from .embeddings import DEFAULT_MODEL
from api.utils.logging_utils import get_logger, logging_context

logger = get_logger("api.services.retrieve")


def _as_vector(embedding: np.ndarray | Iterable[float]) -> list[float]:
    array = np.asarray(embedding, dtype=np.float32)
    if array.ndim != 1:
        array = array.reshape(-1)
    return array.tolist()


def _vector_literal(vector: Sequence[float]) -> str:
    """Serialize a vector for pgvector queries.

    asyncpg does not automatically coerce Python sequences to the pgvector type,
    so we emit the JSON representation that pgvector accepts, matching the
    format used when persisting embeddings.

    :param vector:
    :return:
    """

    return json.dumps([float(component) for component in vector], ensure_ascii=False, separators=(",", ":"))


def _resolve_url(row: asyncpg.Record) -> str | None:
    raw = row["raw_json"] or {}
    issue_payload = raw.get("issue") if isinstance(raw,dict) else None
    if isinstance(issue_payload, dict):
        html_url = issue_payload.get("html_url") or issue_payload.get("url") or issue_payload.get("self")
    elif isinstance(raw, dict):
        html_url = raw.get("html_url") or raw.get("self")
    else:
        html_url = None
    if html_url:
        return html_url
    source = row["source"]
    repo = row["repo"]
    external_key = row["external_key"]
    if source == "github" and repo and external_key:
        _, _, maybe_number = external_key.partition("#")
        if maybe_number.isdigit():
            return f"https://github.com/{repo}/issues/{maybe_number}"
    return None


def _row_to_result(row: asyncpg.Record, score: float) -> RetrievalResult:
    return RetrievalResult(
        issue_id=row["id"],
        title=row["title"],
        score=score,
        url=_resolve_url(row),
    )


async def vector_search(
        pool: asyncpg.Pool,
        embedding: np.ndarray,
        limit: int = 10,
        model: str = DEFAULT_MODEL,
) -> Sequence[RetrievalResult]:
    vector = _as_vector(embedding)
    vector_param = _vector_literal(vector)
    with logging_context(strategy="vector", limit=limit, model=model):
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT i.id,
                       i.title,
                       i.source,
                       i.external_key,
                       i.repo,
                       i.project,
                       i.raw_json,
                       iv.embedding <-> $1 AS distance
                FROM issue_vectors iv
                JOIN issues i ON i.id = iv.issue_id
                WHERE iv.model = $2
                ORDER BY iv.embedding <-> $1
                LIMIT $3
                """,
                vector,
                vector_param,
                model,
                limit,
            )
        logger.info("vector search completed", extra={"context": {"row_count": len(rows)}})
    results: list[RetrievalResult] = []
    for row in rows:
        distance = float(row["distance"])
        score = 1.0 / (1.0 + max(distance, 0.0))
        results.append(_row_to_result(row, score))
    return results


async def hybrid_search(
        pool: asyncpg.Pool,
        embedding: np.ndarray | Iterable[float],
        query: str,
        limit: int = 10,
        alpha: float = 0.5,
        model: str = DEFAULT_MODEL,
) -> Sequence[RetrievalResult]:
    vector = _as_vector(embedding)
    vector_param = _vector_literal(vector)
    with logging_context(strategy="hybrid", limit=limit, model=model, alpha=alpha):
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH vector_candidates AS (
                    SELECT iv.issue_id,
                           1 / (1 + (iv.embedding <-> $1)) AS vector_score
                    FROM issue_vectors iv
                    WHERE iv.model = $5
                    ORDER BY iv.embedding <-> $1
                    LIMIT $2
                ),
                text_candidates AS (
                    SELECT i.id,
                           ts_rank_cd(search_vector, plainto_tsquery('english', $3)) AS text_score
                    FROM issues i
                    WHERE search_vector @@ plainto_tsquery('english', $3)
                    ORDER BY text_score DESC
                    LIMIT $2
                )
                SELECT i.id,
                       i.title,
                       i.source,
                       i.external_key,
                       i.repo,
                       i.project,
                       i.raw_json,
                       COALESCE(vc.vector_score, 0) AS vector_score,
                       COALESCE(tc.text_score, 0) AS text_score
                FROM issues i
                LEFT JOIN vector_candidates vc ON vc.issue_id = i.id
                LEFT JOIN text_candidates tc on tc.id = i.id
                WHERE vc.issue_id IS NOT NULL OR tc.id IS NOT NULL
                ORDER BY (COALESCE(vc.vector_score, 0) * $4 + COALESCE(tc.text_score, 0) * (1 - $4)) DESC
                LIMIT $2
                """,
                vector,
                vector_param,
                limit,
                query,
                alpha,
                model,
            )
        logger.info("Hybrid search completed", extra={"context": {"row_count": len(rows)}})
    results: list[RetrievalResult] = []
    for row in rows:
        vector_score = float(row["vector_score"])
        text_score = float(row["text_score"])
        blended = vector_score * alpha + text_score * (1 - alpha)
        results.append(_row_to_result(row, blended))
    return results

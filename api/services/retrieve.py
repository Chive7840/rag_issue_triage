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


def _vector_sql_literal(vector: Sequence[float]) -> str:
    """Return a SQL literal that casts the vector to the pgvector type."""

    literal = _vector_literal(vector)
    # json.dumps never produces single quotes, but double the character just in case
    # to remain safe when interpolating into SQL.
    escaped = literal.replace("'", "''")
    return f"'{escaped}'::vector"


def _row_value(row: asyncpg.Record, key: str, default: object | None = None) -> object | None:
    """Return a value from an asyncpg.Record or plain mapping without KeyErrors."""

    getter = getattr(row, "get", None)
    if callable(getter):
        try:
            return getter(key, default)     # type: ignore[misc]
        except TypeError:
            # asyncpg.Record.get only accepts (key, default); if we passed
            # incompatible defaults fall back to __getitem__.
            pass
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _resolve_url(row: asyncpg.Record) -> str | None:
    """Best effort construction of an issue URL from a search row."""

    def _get(key: str, default: object | None = None) -> object | None:
        try:
            return row.get(key, default)    # type: ignore[return-value]
        except AttributeError:
            try:
                return row[key]
            except (KeyError, TypeError):
                return default

    raw = _get("raw_json") or {}
    issue_payload = raw.get("issue") if isinstance(raw, dict) else None
    if isinstance(issue_payload, dict):
        html_url = (
                issue_payload.get("html_url")
                or issue_payload.get("url")
                or issue_payload.get("self")
        )
    elif isinstance(raw, dict):
        html_url = raw.get("html_url") or raw.get("self")
    else:
        html_url = None
    if html_url:
        return html_url

    source = (_get("source") or "").lower()
    repo = _get("repo")
    project = _get("project")
    external_key = _get("external_key")
    issue_id = _get("id")

    if source == "github" and repo and external_key:
        _, _, maybe_number = str(external_key).partition("#")
        if maybe_number.isdigit():
            return f"https://github.com/{repo}/issues/{maybe_number}"
        if str(issue_id).isdigit():
            return f"https://github.com/{repo}/issues/{issue_id}"

    if project:
        key = external_key or issue_id
        if key is not None:
            return f"https://github.com/{repo}/issues/{issue_id}"

    if repo and str(issue_id).isdigit():
        return f"https://github.com/{repo}/issues/{issue_id}"

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
    vector_sql = _vector_sql_literal(vector)
    query = f"""
        SELECT i.id,
               i.title,
               i.source,
               i.external_key,
               i.repo,
               i.project,
               i.raw_json,
               iv.embedding <-> {vector_sql} AS distance
        FROM issue_vectors iv
        JOIN issues i ON i.id = iv.issue_id
        WHERE iv.model = $1
        ORDER BY iv.embedding <-> '{vector_sql}'::vector
        LIMIT $2
    """
    params: tuple[object, ...] = (model, limit)
    with logging_context(strategy="vector", limit=limit, model=model):
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        logger.info("vector search completed", extra={"context": {"row_count": len(rows)}})
    results: list[RetrievalResult] = []
    for row in rows:
        distance = float(row["distance"])
        score = max(1.0 - max(distance, 0.0), 0.0)
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
    vector_sql = _vector_sql_literal(vector)
    query_text = f"""
        WITH vector_candidates AS (
            SELECT iv.issue_id,
                   1 / (1 + (iv.embedding <-> {vector_sql})) AS vector_score
            FROM issue_vectors iv
            WHERE iv.model = $4
            ORDER BY iv.embedding <-> {vector_sql}
            LIMIT $1
        ),
        text_candidates AS (
            SELECT i.id,
                   ts_rank_cd(search_vector, plainto_tsquery('english', $2)) AS text_score
            FROM issues i
            WHERE search_vector @@ plainto_tsquery('english', $2)
            ORDER BY text_score DESC
            LIMIT $1
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
        ORDER BY (COALESCE(vc.vector_score, 0) * $3 + COALESCE(tc.text_score, 0) * (1 - $3)) DESC
        LIMIT $1
    """
    params: tuple[object, ...] = (limit, query, alpha, model)
    with logging_context(strategy="hybrid", limit=limit, model=model, alpha=alpha):
        async with pool.acquire() as conn:
            rows = await conn.fetch(query_text, *params)
        logger.info("Hybrid search completed", extra={"context": {"row_count": len(rows)}})
    results: list[RetrievalResult] = []
    for row in rows:
        vector_score = float(row["vector_score"])
        text_score = float(row["text_score"])
        blended = vector_score * alpha + text_score * (1 - alpha)
        results.append(_row_to_result(row, blended))
    return results

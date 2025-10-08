from typing import Any

import numpy as np
import pytest

from api.schemas import RetrievalResult
from api.services import retrieve

class FakeConn:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, query: str, *args: Any):
        self.fetch_calls.append((query, args))
        return self.rows


class FakeAcquire:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> FakeConn:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> None:   # noqa: ANN001
        return None


class FakePool:
    def __init__(self, rows: list[dict[str, Any]]):
        self.conn = FakeConn(rows)

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.conn)


@pytest.mark.asyncio
async def test_vector_search_returns_results_with_urls():
    embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    rows = [
        {"id": 1, "title": "Bug", "repo": "org/repo", "project": None, "distance": 0.2},
        {"id": 2, "title": "Task", "repo": None, "project": "proj", "distance": 0.5},
    ]
    pool = FakePool(rows)

    results = await retrieve.vector_search(pool, embedding, limit=2, model="model")

    assert len(results) == 2
    query_text, params = pool.conn.fetch_calls[0]
    # The vector embedding is interpolated as a pgvector literal and no longer
    # passed as a positional parameter.
    assert "::vector" in query_text
    assert params == ("model", 2)
    first = results[0]
    assert isinstance(first, RetrievalResult)
    assert first.url == "https://github.com/org/repo/issues/1"
    assert pytest.approx(first.score) == 0.8
    second = results[1]
    assert second.url == "https://proj.atlassian.net/browse/2"

@pytest.mark.asyncio
async def test_hybrid_search_combines_scores():
    embedding = np.array([0.1, 0.2, 0.3])
    rows = [
        {
            "id": 10,
            "title": "Hybrid",
            "repo": "org/repo",
            "project": None,
            "vector_score": 0.9,
            "text_score": 0.3,
         }
    ]
    pool = FakePool(rows)

    results = await retrieve.hybrid_search(pool, embedding, query="bug", limit=1, alpha=0.75)

    assert len(results) == 1
    query_text, params = pool.conn.fetch_calls[0]
    assert "::vector" in query_text
    assert params == (1, "bug", 0.75, "sentence-transformers/all-MiniLM-L6-v2")
    result = results[0]
    assert result.url == "https://github.com/org/repo/issues/10"
    assert pytest.approx(result.score) == pytest.approx(0.9 * 0.75 + 0.3 * 0.25)

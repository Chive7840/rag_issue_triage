import pytest

from api.schemas import RetrievalResult
from api.services import rerank

@pytest.mark.asyncio
async def test_noop_reranker_returns_candidates():
    candidates = [RetrievalResult(issue_id=1, title="A Title", score=0.5)]
    rr = rerank.NoOpReranker()

    result = await rr.rerank("query", candidates)

    assert result == candidates

import numpy as np
import pytest

from api.schemas import RetrievalResult, TriageProposal
from api.services import triage

class StubReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[RetrievalResult]]] = []

    async def rerank(self, query: str, candidates):
        self.calls.append((query, list(candidates)))
        return list(reversed(candidates))

class DummyPool:
    def __init__(self, results):
        self.results = results

    def acquire(self):      # pragma: no cover - not used directly in triage.propose
        raise AssertionError("acquire should not be called directly in this test")

@pytest.mark.asyncio
async def test_propose_returns_triage_payload(monkeypatch):
    neighbors = [
        RetrievalResult(issue_id=10, title="Issue-A-10", score=0.9),
        RetrievalResult(issue_id=11, title="Issue-B-11", score=0.8),
    ]

    async def fake_vector_search(pool, embedding, limit):   # noqa: ANN001
        assert isinstance(embedding, np.ndarray)
        assert limit == 3
        return neighbors

    monkeypatch.setattr(triage, "vector_search", fake_vector_search)

    reranker = StubReranker()
    pool = DummyPool(neighbors)
    embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)

    proposal = await triage.propose(pool, issue_id=99, embedding=embedding, reranker=reranker, top_k=3)

    assert isinstance(proposal, TriageProposal)
    assert list(proposal.labels) == ["needs-triage"]
    assert proposal.similar[0].issue_id == 11
    assert reranker.calls and reranker.calls[0][0] == "issue_triage"
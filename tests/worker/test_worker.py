import numpy as np
import pytest

from worker import worker as worker_module

class FakeConn:
    def __init__(self, issue_exists=True, vector_exists=False):
        self.issue_exists = issue_exists
        self.vector_exists = vector_exists
        self.fetchrow_calls = []
        self.execute_calls = []

    async def fetchrow(self, query, *args):     # noqa: ANN001
        self.fetchrow_calls.append((query, args))
        if "FROM issues" in query:
            return {"title": "T", "body": "B"} if self.issue_exists else None
        if "SELECT 1 FROM issue_vectors" in query:
            return {"exists": 1} if self.vector_exists else None
        return None

    async def execute(self, query, *args):      # noqa: ANN001
        self.execute_calls.append((query, args))

class FakeAcquire:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> FakeConn:
        return self.conn

    async def __aexit__(self, exc_type, exc, tb) -> None:   # noqa: ANN001
        return None

class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.conn)

@pytest.mark.asyncio
async def test_process_job_inserts_embeddings(monkeypatch):
    conn = FakeConn(issue_exists=True, vector_exists=False)
    pool = FakePool(conn)

    monkeypatch.setattr(
        worker_module.embeddings,
        "embedding_for_issue",
        lambda title, body: np.array([0.1, 0.2], dtype=np.float32),
    )

    await worker_module.process_job(pool, {"issue_id": 5, "force": False})

    assert any("INSERT INTO issue_vectors" in call[0] for call in conn.execute_calls)
    assert any("INSERT INTO similar" in call[0] for call in conn.execute_calls)

@pytest.mark.asyncio
async def test_process_job_skips_when_issue_missing(monkeypatch):
    conn = FakeConn(issue_exists=False)
    pool = FakePool(conn)

    await worker_module.process_job(pool, {"issue_id": 5})

    assert not conn.execute_calls

@pytest.mark.asyncio
async def test_process_job_skips_existing_vector(monkeypatch):
    conn = FakeConn(issue_exists=False)
    pool = FakePool(conn)

    await worker_module.process_job(pool, {"issue_id": 5, "force": False})

    assert not conn.execute_calls
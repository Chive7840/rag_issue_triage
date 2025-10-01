from datetime import datetime, timezone
from typing import Any

import pytest

from api.schemas import IssuePayload
from api.services import ingest

class FakeConn:
    def __init__(self, expected_id: int = 42) -> None:
        self.expected_id = expected_id
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, query: str, *args: Any):
        self.fetchrow_calls.append((query, args))
        return {"id": self.expected_id}

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
async def test_store_issue_upserts_and_returns_id():
    now = datetime.now(timezone.utc)
    payload = IssuePayload(
        source="github",
        external_key="octo/hello#102",
        title="Bug#102",
        body="Thing is broken.",
        repo="octo/hello",
        project=None,
        status="open",
        created_at=now,
        raw_json={"issue": {"id": 102}}
    )
    conn = FakeConn(expected_id=77)
    pool = FakePool(conn)

    issue_id = await ingest.store_issue(pool, payload)

    assert issue_id == 77
    assert len(conn.fetchrow_calls) == 1
    _, args = conn.fetchrow_calls[0]
    assert args[0] == "github"
    assert args[1] == "octo/hello#102"
    assert args[2] == "Bug#102"

def test_normalize_github_issue_builds_payload():
    created = datetime.now(timezone.utc)
    payload = {
        "issue": {
            "id": 100,
            "title": "Example 100",
            "body": "Body of Example 100.",
            "state": "open",
            "number": 4,
            "created_at": created.isoformat(),
        },
        "repository": {"full_name": "org/repo"},
    }

    normalized = ingest.normalize_github_issue(payload)

    assert normalized.source == "github"
    assert normalized.external_key == "org/repo#4"
    assert normalized.title == "Example 100"
    assert normalized.body == "Body of Example 100."
    assert normalized.repo == "org/repo"
    assert normalized.status == "open"

def test_normalize_jira_issue_builds_payload():
    created = datetime.now(timezone.utc)
    payload = {
        "issue": {
            "id": "34",
            "key": "TEST-34",
            "fields": {
                "summary": "Example of summary.",
                "description": "Body of description.",
                "project": {"key": "TEST"},
                "status": {"name": "To Do"},
                "created": created.isoformat(),
            },
        }
    }

    normalized = ingest.normalize_jira_issue(payload)

    assert normalized.source == "jira"
    assert normalized.external_key == "TEST-34"
    assert normalized.project == "TEST"
    assert normalized.status == "To Do"

@pytest.mark.asyncio
async def test_enqueue_embedding_job_pushes_payload(monkeypatch):
    pushed: list[str] = []

    class FakeRedis:
        async def rpush(self, key: str, payload: str) -> None:
            pushed.append((key, payload))

    redis = FakeRedis()

    await ingest.enqueue_embedding_job(redis, issue_id=5, force=True)

    assert pushed
    key, payload = pushed[0]
    assert key == "triage:embed"
    assert payload == "{\"issue_id\": 5, \"force\": true}"

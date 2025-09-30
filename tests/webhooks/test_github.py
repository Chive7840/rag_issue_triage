import hashlib
import hmac
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.webhooks import github

def make_app():
    app = FastAPI()
    app.include_router(github.router)
    app.state.github_webhook_secret = "secret"
    app.state.json_loads = json.loads
    app.state.db_pool = object()
    app.state.redis = object()
    return app

def sign(body: bytes) -> str:
    digest = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"

def test_github_webhook_processes_issue(monkeypatch):
    app = make_app()
    payload = {"issue": {"id": 123, "title": "Bug#123"}}
    body = json.dumps(payload).encode()
    called = {}

    async def fake_store(pool, normalized):                 # noqa: ANN001
        called["store"] = (pool, normalized)
        return 42

    async def fake_enqueue(redis, issue_id, force=False):   # noqa: ANN001
        called.setdefault("enqueue", []).append((redis, issue_id, force))

    monkeypatch.setattr(github.ingest, "normalize_github_issue", lambda payload: payload)
    monkeypatch.setattr(github.ingest, "store_issue", fake_store)
    monkeypatch.setattr(github.ingest, "enqueue_embedding_job", fake_enqueue)

    client = TestClient(app)
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": sign(body),
            "X-GitHub-Event": "issues",
        },
    )

    assert response.status_code == 200
    assert called["store"][0] is app.state.db_pool
    assert called["enqueue"][0][0] is app.state.redis
    assert called["enqueue"][0][1] == 42

def test_github_webhook_rejects_bad_signature():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/webhooks/github",
        content=b"{}",
        headers={
            "X-Hub-Signature-256": "sha256=bad",
            "X-GitHub-Event": "issues",
        },
    )

    assert response.status_code == 401

def test_github_health_endpoint():
    app = make_app()
    client = TestClient(app)

    response = client.get("/webhooks/github/health")

    assert response.status_code == 200
    assert response.json()["details"]["source"] == "github"
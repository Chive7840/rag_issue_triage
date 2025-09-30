import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.webhooks import jira

def make_app(secret: str | None):
    app = FastAPI()
    app.include_router(jira.router)
    app.state.jira_webhook_secret = secret
    app.state.db_pool = object()
    app.state.redis = object()
    return app

def test_jira_webhook_accepts_valid_identifier(monkeypatch):
    app = make_app("secret")
    payload = {"issue": {"id": "1", "key": "JIRA-1"}}
    called = {}

    monkeypatch.setattr(jira.ingest, "normalize_jira_issue", lambda data: data)

    async def fake_store(pool, normalized):     # noqa: ANN001
        called["store"] = (pool, normalized)
        return 10

    async def fake_enqueue(redis, issue_id, force=False):   # noqa: ANN001
        called.setdefault("enqueue", []).append((redis, issue_id, force))

    monkeypatch.setattr(jira.ingest, "store_issue", fake_store)
    monkeypatch.setattr(jira.ingest, "enqueue_embedding_job", fake_enqueue)

    client = TestClient(app)
    response = client.post(
        "/webhooks/jira",
        json=payload,
        headers={"X-Atlassian-Webhook-Identifier": "secret"},
    )

    assert response.status_code == 200
    assert called["store"][0] is app.state.db_pool
    assert called["enqueue"][0][0] is app.state.redis

def test_jira_webhook_rejects_invalid_identifier():
    app = make_app("secret")
    client = TestClient(app)

    response = client.post(
        "/webhooks/jira",
        json={"issue": {"id": 100}},
        headers={"X-Atlassian-Webhook-Identifier": "wrong"},
    )

    assert response.status_code == 401

def test_jira_health_endpoint():
    app = make_app("secret")
    client = TestClient(app)

    response = client.get("/webhooks/jira/health")

    assert response.status_code == 200
    assert response.json()["details"]["source"] == "jira"

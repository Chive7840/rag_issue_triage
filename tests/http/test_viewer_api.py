from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.http import viewer
from api.services import retrieve


@pytest.fixture
def test_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    app = FastAPI()
    app.include_router(viewer.router)
    app.state.db_pool = object()

    async def fake_list_routes(pool):  # noqa: ANN001
        assert pool is app.state.db_pool
        return [
            "/gh/foo/bar/issues/1",
            "/jira/site/ABC/ABC-1",
        ]

    async def fake_fetch(pool, route):  # noqa: ANN001
        assert pool is app.state.db_pool
        if route == "/gh/foo/bar/issues/1":
            return {
                "id": 1,
                "source": "github",
                "route": "/gh/foo/bar/issues/1",
                "origin_url": "https://github.com/foo/bar/issues/1",
                "title": "Example",
                "body": "Body",
                "body_html": "<p>Body</p>",
                "repo": "foo/bar",
                "project": None,
                "status": "open",
                "priority": "P1",
                "labels": ["bug"],
                "created_at": None,
                "determinism": "Synthetic. Source: github.",
                "comments": [],
            }
        return None

    async def fake_search(pool, *, filters, limit=50):  # noqa: ANN001
        assert pool is app.state.db_pool
        assert filters["q"] == "auth"
        return [
            {
                "id": 2,
                "source": "github",
                "route": "/gh/foo/bar/issues/2",
                "origin_url": "https://github.com/foo/bar/issues/2",
                "title": "Auth bug",
                "status": "open",
                "priority": "P0",
                "labels": ["bug"],
                "repo": "foo/bar",
                "project": None,
                "created_at": None,
            }
        ]

    monkeypatch.setattr(retrieve, "list_canonical_routes", fake_list_routes)
    monkeypatch.setattr(retrieve, "fetch_issue_by_route", fake_fetch)
    monkeypatch.setattr(retrieve, "search_viewer_issues", fake_search)
    return app


def test_routes_endpoint_returns_routes(test_app: FastAPI) -> None:
    client = TestClient(test_app)
    response = client.get("/api/routes")
    assert response.status_code == 200
    assert response.json() == [
        {"route": "/gh/foo/bar/issues/1"},
        {"route": "/jira/site/ABC/ABC-1"},
    ]


def test_issue_by_route_returns_record(test_app: FastAPI) -> None:
    client = TestClient(test_app)
    response = client.get("/api/issues/by-route/%2Fgh%2Ffoo%2Fbar%2Fissues%2F1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["route"] == "/gh/foo/bar/issues/1"
    assert payload["origin_url"] == "https://github.com/foo/bar/issues/1"


def test_issue_by_route_unknown_returns_hint(test_app: FastAPI) -> None:
    client = TestClient(test_app)
    response = client.get("/api/issues/by-route/%2Fgh%2Fmissing%2Frepo%2Fissues%2F42")
    assert response.status_code == 404
    assert response.json() == {
        "error": "route not found",
        "hint": "Use /api/routes or /api/issues/search to discover available issues.",
    }


def test_search_endpoint_returns_items(test_app: FastAPI) -> None:
    client = TestClient(test_app)
    response = client.get("/api/issues/search", params={"q": "auth"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["route"] == "/gh/foo/bar/issues/2"
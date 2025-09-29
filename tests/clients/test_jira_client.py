from http.client import responses
from types import SimpleNamespace

import pytest

from api.clients import jira

class DummyResponse:
    def __init__(self, payload=None):
        self._payload = payload
        self.called = None

    def json(self):
        return self._payload

    def raise_for_status(self):
        self.called = True

@pytest.mark.asyncio
async def test_fetch_issue_calls_get(monkeypatch):
    response = DummyResponse({"key": "JIRA_REST-1"})

    async def fake_get(url):
        assert url == "/rest/api/3/issue/JIRA_REST-1"
        return response

    async def fake_close():
        pass

    fake_client = SimpleNamespace(get=fake_get, post=None, put=None, aclose=fake_close)
    monkeypatch.setattr(jira.httpx, "AsyncClient", lambda **kwargs: fake_client)

    client = jira.JiraClient(base_url="https://example.atlassian.net", email="an@email.com", api_token="an_api_token")
    result = await client.fetch_issue("JIRA_REST-1")
    await client.close()

    assert result == {"key": "JIRA_REST-1"}
    assert response.called

@pytest.mark.asyncio
async def test_add_comment_posts_body(monkeypatch):
    captured = {}

    async def fake_post(url, json):
        resp = DummyResponse()
        captured["url"] = url
        captured["json"] = json
        captured["response"] = resp
        return resp

    async def fake_close():
        pass

    fake_client = SimpleNamespace(get=None, post=fake_post, put=None, aclose=fake_close)
    monkeypatch.setattr(jira.httpx, "AsyncClient", lambda **kwargs: fake_client)

    client = jira.JiraClient(base_url="https://example", email="an@email.com", api_token="an_api_token")
    await client.add_comment("COMMENT-1", "comment_body1")
    await client.close()

    assert captured["url"] == "/rest/api/3/issue/COMMENT-1/comment"
    assert captured["json"] == {"body": "comment_body1"}
    assert captured["response"].called

@pytest.mark.asyncio
async def test_transition_posts_payload(monkeypatch):
    captured = {}

    async def fake_post(url, json):  # noqa: ANN001
        resp = DummyResponse()
        captured["url"] = url
        captured["json"] = json
        captured["response"] = resp
        return resp

    async def fake_close():
        pass

    fake_client = SimpleNamespace(get=None, post=fake_post, put=None, aclose=fake_close)
    monkeypatch.setattr(jira.httpx, "AsyncClient", lambda **kwargs: fake_client)

    client = jira.JiraClient(base_url="https://tranisitionExample", email="an@email.com", api_token="an_api_token")
    await client.transition("TRANSIT-1", "72")
    await client.close()

    assert captured["url"] == "/rest/api/3/issue/TRANSIT-1/transitions"
    assert captured["json"] == {"transition": {"id": "72"}}
    assert captured["response"].called

@pytest.mark.asyncio
async def test_assign_puts_payload(monkeypatch):
    captured = {}

    async def fake_put(url, json):  # noqa: ANN001
        resp = DummyResponse()
        captured["url"] = url
        captured["json"] = json
        captured["response"] = resp
        return resp

    async def fake_close():
        pass

    fake_client = SimpleNamespace(get=None, post=None, put=fake_put, aclose=fake_close)
    monkeypatch.setattr(jira.httpx, "AsyncClient", lambda **kwargs: fake_client)

    client = jira.JiraClient(base_url="https://assignExample", email="an@email.com", api_token="an_api_token")
    await client.assign("ASSIGN-1", "aUserID")
    await client.close()

    assert captured["url"] == "/rest/api/3/issue/ASSIGN-1/assignee"
    assert captured["json"] == {"accountId": "aUserID"}
    assert captured["response"].called

@pytest.mark.asyncio
async def test_with_client_yields_and_closes(monkeypatch):
    closed = False

    class FakeClient(jira.JiraClient):
        async def close(self):  # type: ignore[override]
            nonlocal closed
            closed = True

    monkeypatch.setattr(jira, "JiraClient", FakeClient)

    context = jira.with_client("https://yieldCloseTest", email="an@email.com", api_token="an_api_token")
    client = await context.__anext__()
    assert isinstance(client, FakeClient)
    with pytest.raises(StopAsyncIteration):
        await context.__anext__()
    assert closed
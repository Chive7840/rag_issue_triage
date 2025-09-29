from types import SimpleNamespace

import pytest

from api.clients import github

class DummyResponse:
    def __init__(self, payload):
        self._payload = payload
        self.called = False

    def json(self):
        return self._payload

    def raise_for_status(self):
        self.called = True

@pytest.mark.asyncio
async def test_fetch_issue_uses_get(monkeypatch):
    dummy_resp = DummyResponse({"id": 1})

    async def fake_get(url):    #noqa: ANN001
        assert url == "/repos/org/repo/issues/1"
        return dummy_resp

    async def fake_close():
        pass

    fake_client = SimpleNamespace(get=fake_get, post=None, aclose=fake_close)
    monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kwargs: fake_client)

    client = github.GitHubClient(token="token")
    result = await client.fetch_issue("org/repo", 1)

    assert result == {"id": 1}
    assert dummy_resp.called
    await client.close()

@pytest.mark.asyncio
async def test_add_labels_posts_payload(monkeypatch):
    captured = {}

    async def fake_post(url, json):     # noqa: ANN001
        resp = DummyResponse(None)
        captured["url"] = url
        captured["json"] = json
        captured["response"] = resp
        return resp

    async def fake_close():
        pass

    fake_client = SimpleNamespace(get=None, post=fake_post, aclose=fake_close)
    monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kwargs: fake_client)

    client = github.GitHubClient(token="token")
    await client.add_labels("org/repo", 2, ["bug"])
    await client.close()

    assert captured["url"] == "/repos/org/repo/issues/2/labels"
    assert captured["json"] == {"labels": ["bug"]}
    assert captured["response"].called

@pytest.mark.asyncio
async def test_assign_issue_posts_assignees(monkeypatch):
    captured = {}

    async def fake_post(url, json):     # noqa: ANN001
        resp = DummyResponse(None)
        captured["url"] = url
        captured["json"] = json
        captured["response"] = resp
        return resp

    async def fake_close():
        pass

    fake_client = SimpleNamespace(get=None, post=fake_post, aclose=fake_close)
    monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kwargs: fake_client)

    client = github.GitHubClient(token="token")
    await client.assign_issue("org/repo", 3, ["user"])
    await client.close()

    assert captured["url"] == "/repos/org/repo/issues/3/assignees"
    assert captured["json"] == {"assignees": ["user"]}
    assert captured["response"].called

@pytest.mark.asyncio
async def test_create_comment_posts_body(monkeypatch):
    captured = {}

    async def fake_post(url, json):     # noqa: ANN001
        resp = DummyResponse(None)
        captured["url"] = url
        captured["json"] = json
        captured["response"] = resp
        return resp

    async def fake_close():
        pass

    fake_client = SimpleNamespace(get=None, post=fake_post, aclose=fake_close)
    monkeypatch.setattr(github.httpx, "AsyncClient", lambda **kwargs: fake_client)

    client = github.GitHubClient(token="token")
    await client.create_comment("org/repo", 4, "body")
    await client.close()

    assert captured["url"] == "/repos/org/repo/issues/4/comments"
    assert captured["json"] == {"body": "body"}
    assert captured["response"].called

@pytest.mark.asyncio
async def test_with_client_yields_and_closes(monkeypatch):
    closed = False

    class FakeClient(github.GitHubClient):
        async def close(self):
            nonlocal closed
            closed = True

    monkeypatch.setattr(github, "GitHubClient", FakeClient)

    context = github.with_client("token")
    client = await context.__anext__()
    assert isinstance(client, FakeClient)
    with pytest.raises(StopAsyncIteration):
        await context.__anext__()
    assert closed

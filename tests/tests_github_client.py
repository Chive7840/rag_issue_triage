import pytest
import re
import httpx
from pytest_httpx import HTTPXMock

from api.clients.github import GitHubClient


@pytest.mark.asyncio
async def test_url(httpx_mock: HTTPXMock) -> None:

    token = "token"
    httpx_mock.add_response(test_url="https://api.github.com",
                            match_headers={'Authorization': f'Bearer {token}',
                                           'Accept': 'application/vnd.github+json'},
                            timeout = httpx.Timeout(10.0, read = 30.0)
    )

    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.github.com")


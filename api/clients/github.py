"""GitHub REST client for applying triage decisions and fetching issues."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Mapping

import httpx

from api.utils.logging_utils import get_logger, logging_context

logger = get_logger("api.clients.github")

class GitHubClient:
    """Minimal GitHub REST API wrapper following official docs."""

    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url = self._base_url,
            headers = {
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
            },
            timeout = httpx.Timeout(10.0, read = 30.0),
        )

    async def close(self) -> None:
        await self._client.aclose()


    async def fetch_issue(self, repo: str, number: int) -> Mapping[str, Any]:
        url = f"/repos/{repo}/issues/{number}"
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def add_labels(self, repo: str, number: int, labels: list[str]) -> None:
        url = f"/repos/{repo}/issues/{number}/labels"
        resp = await self._client.post(url, json={"labels": labels})
        resp.raise_for_status()
        with logging_context(repo=repo, number=number, action="add_labels"):
            logger.info("Applied labels", extra={"context": {"labels": labels}})

    async def create_comment(self, repo: str, number: int, body: str) -> None:
        url = f"/repos/{repo}/issues/{number}/comments"
        resp = await self._client.post(url, json={"body": body})
        resp.raise_for_status()
        with logging_context(repo=repo, number=number, action="create_comment"):
            logger.info("Created comment")

    async def assign_issue(self, repo: str, number: int, assignees: list[str]) -> None:
        url = f"/repos/{repo}/issues/{number}/assignees"
        resp = await self._client.post(url, json={"assignees": assignees})
        resp.raise_for_status()
        with logging_context(repo=repo, number=number, action="assign_issue"):
            logger.info("Assigned issue", extra={"context": {"assignees": assignees}})

@asynccontextmanager
async def with_client(token: str) -> GitHubClient:
    client = GitHubClient(token=token)
    try:
        yield client
    finally:
        await client.close()
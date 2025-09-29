"""Jira cloud REST client covering transitions, comments, and fetches."""
from __future__ import annotations

from custom_logger.logger import Logger
import logging
# Sets the default logging class
logging.setLoggerClass(Logger)
# Instantiates the logger with a built-in variable that provides the module's name
logger = logging.getLogger(__name__)

from typing import Any, Mapping

import httpx

class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Accept": "application/json",
            },
            auth=(email, api_token),
            timeout=httpx.Timeout(10.0, read=30.0),
        )

    async def close(self) -> None:
        """ Provides a function to ensure the client closes after it has been used."""
        await self._client.aclose()

    async def fetch_issue(self, key: str) -> Mapping[str, Any]:
        """ This function utilizes a key to fetch a json with work items that match the key"""
        resp = await self._client.get(f"/rest/api/3/issue/{key}")
        resp.raise_for_status()
        return resp.json()

    async def add_comment(self, key: str, body: str) -> None:
        """This function allows the addition of comments to a specified work item."""
        resp = await self._client.post(
            f"/rest/api/3/issue/{key}/comment",
            json={"body": body},
        )
        resp.raise_for_status()
        logger.info("Created Jira comment on %s", key)

    async def transition(self, key: str, transition_id: str) -> None:
        """Describes the statuses the specified work item can move to from its current state."""
        resp = await self._client.post(
            f"/rest/api/3/issue/{key}/transitions",
            json={"transition": {"id": transition_id}},
        )
        resp.raise_for_status()
        logger.info("Transitioned %s via %s", key, transition_id)

    async def assign(self, key: str, account_id: str) -> None:
        """This function allows for users to be assigned to work items."""
        resp = await self._client.put(
            f"/rest/api/3/issue/{key}/assignee",
            json={"accountId": account_id},
        )
        resp.raise_for_status()
        logger.info("Assigned %s to %s", key, account_id)

async def with_client(base_url: str, email: str, api_token: str) -> JiraClient:
    client = JiraClient(base_url=base_url, email=email, api_token=api_token)
    try:
        yield client
    finally:
        await client.close()

"""Ingestion helpers for GitHub and Jira events."""
from __future__ import annotations

import json
from datetime import datetime, timezone, UTC
from typing import Any

import asyncpg

from ..schemas import IssuePayload

from api.utils.logging_utils import get_logger, logging_context

logger = get_logger("api.services.ingest")

async def store_issue(pool: asyncpg.Pool, issue: IssuePayload) -> int:
    """Insert or update an issue row and return its primary key."""

    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            """
            INSERT INTO issues (source, external_key, title, body, repo, project, status, created_at, raw_json)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (source, external_key) DO UPDATE SET
                title = EXCLUDED.title,
                body = EXCLUDED.body,
                repo = EXCLUDED.repo,
                project = EXCLUDED.project,
                status = EXCLUDED.status,
                raw_json = EXCLUDED.raw_json
            RETURNING id
            """,
            issue.source,
            issue.external_key,
            issue.title,
            issue.body,
            issue.project,
            issue.status,
            issue.created_at,
            issue.raw_json,
        )
    if record is None:
        raise RuntimeError("Failed to upsert issue payload")
    with logging_context(source=issue.source, external_key=issue.external_key):
        logger.debug("Upserted issue")
    return int(record["id"])

def _parse_datetime(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(tz=UTC)
    normalized = raw.replace("z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(tz=UTC)


def normalize_github_issue(payload: dict[str, Any]) -> IssuePayload:
    issue = payload.get("issue") or payload
    repository = payload.get("repository", {})
    repo_full_name = repository.get("full_name")
    body = issue.get("body") or ""
    created_at = issue.get("created_at") or datetime.now(timezone.utc).isoformat()
    number = issue.get("number") or issue.get("id")
    external_key = f"{repo_full_name}#{number}" if repo_full_name and number is not None else str(issue.get("id"))
    return IssuePayload(
        source="github",
        external_key=external_key,
        title=issue.get("title", ""),
        body=body,
        repo=repo_full_name,
        project=None,
        status=issue.get("state"),
        created_at=created_at,
        raw_json=payload,
    )

def normalize_jira_issue(payload: dict[str, Any]) -> IssuePayload:
    issue = payload.get("issue") or payload
    fields = issue.get("fields", {})
    created_at = fields.get("created") or datetime.now(timezone.utc).isoformat()
    return IssuePayload(
        source="jira",
        external_key=issue.get("key") or str(issue.get("id")),
        title=fields.get("summary", ""),
        body=(fields.get("description") or ""),
        repo=None,
        project=fields.get("project", {}).get("key"),
        status=fields.get("status", {}).get("name"),
        created_at=datetime.fromisoformat(created_at.replace("z", "+00:00")),
        raw_json=payload,
    )

async def enqueue_embedding_job(redis, issue_id: int, force: bool = False) -> None:
    payload = json.dumps({"issue_id": issue_id, "force": force})
    await redis.rpush("triage:embed", payload)
    with logging_context(issue_id=issue_id):
        logger.debug("Enqueued embedding job")

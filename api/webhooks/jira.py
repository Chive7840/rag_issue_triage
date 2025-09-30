"""FastAPI router for Jira Cloud webhooks."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Header, Request, status

from ..schemas import HealthResponse
from ..services import ingest

import logging
from custom_logger.logger import Logger
logging.setLoggerClass(Logger)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["jira"])


@router.post("/jira")
async def handle_jira(
        request: Request,
        x_atlassian_webhook_identifier: str = Header(None, alias="X-Atlassian-Webhook-Identifier"),
):
    expected = request.app.state.jira_webhook_secret
    if expected and x_atlassian_webhook_identifier != expected:
        logger.warning("Jira webhook identifier mismatch")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid identifier")
    payload = await request.json()
    pool = request.app.state.db_pool
    redis = request.app.state.redis
    normalized = ingest.normalize_jira_issue(payload)
    issue_id = await ingest.store_issue(pool, normalized)
    await ingest.enqueue_embedding_job(redis, issue_id)
    return {"ok": True}

@router.get("/jira/health", response_model=HealthResponse)
async def jira_health() -> HealthResponse:
    return HealthResponse(status="ok", details={"source": "jira"})

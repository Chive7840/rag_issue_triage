"""FastAPI router for GitHub webhooks -- follows the official GitHub docs."""
from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

#from ..schemas import HealthResponse TODO: Uncomment after the module is created
#from ..services import ingest        TODO: Uncomment after the module is created

import logging
from custom_logger.logger import Logger
logging.setLoggerClass(Logger)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["github"])

async def verify_signature(
        request: Request,
        x_hub_signature_256: str = Header(..., alias="X-Hub-Signature-256"),
) -> bytes:
    secret = request.app.state.github_webhook_secret
    body = await request.body()
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_hub_signature_256):
        logger.warning("Github signature mismatch")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature")
    return body

@router.post("/github")
async def handle_github(
        request: Request,
        body: bytes = Depends(verify_signature),
        x_github_event: str = Header(..., alias="X-GitHub-Event"),
):
    payload = request.app.state.json_loads(body)
    pool = request.app.state.db_pool
    redis = request.app.state.redis
    event = x_github_event

    if event in {"issues", "issue_comment", "pull_request"}:
        normalized = ingest.normalize_github_issue(payload)
        issue_id = await ingest.store_issue(pool, normalized)
        await ingest.enqueue_embedding_job(redis, issue_id)
    else:
        logger.info("Ignoring GitHub event %s", event)
    return {"ok": True}

@router.get("/github/health", response_model=HealthResponse)
async def github_health() -> HealthResponse:
    return HealthResponse(status="ok", details={"source": "github"})

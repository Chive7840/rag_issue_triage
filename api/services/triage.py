"""Generate triage proposals from retrieved context."""
from __future__ import annotations

import asyncpg
import numpy as np

from ..schemas import TriageProposal
from .retrieve import vector_search
from api.utils.logging_utils import get_logger, logging_context

logger = get_logger("api.services.triage")

async def propose(
        pool: asyncpg.Pool,
        issue_id: int,
        embedding: np.ndarray,
        reranker,
        top_k: int = 5,
) -> TriageProposal:
    with logging_context(issue_id=issue_id, top_k=top_k):
        logger.info("Generating proposal from neighbors")
        neighbors = await vector_search(pool, embedding, limit=top_k)
        reranked = await reranker.rerank("issue_triage", neighbors)
        logger.info("Proposal assembled", extra={"context": {"neighbor_count": len(reranked)}})
    labels = ["needs-triage"]
    assignees: list[str] = []
    summary = "Similar issues suggest investigating related regressions."
    return TriageProposal(
        labels=labels,
        assignee_candidates=assignees,
        summary=summary,
        similar=reranked,
    )
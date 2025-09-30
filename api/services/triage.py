"""Generate triage proposals from retrieved context."""
from __future__ import annotations

import logging
from custom_logger.logger import Logger
logging.setLoggerClass(Logger)
logger = logging.getLogger(__name__)

import asyncpg
import numpy as np

from ..schemas import TriageProposal
from .retrieve import vector_search

async def propose(
        pool: asyncpg.Pool,
        issue_id: int,
        embedding: np.ndarray,
        reranker,
        top_k: int = 5,
) -> TriageProposal:
    neighbors = await vector_search(pool, embedding, limit=top_k)
    reranked = await reranker.rerank("issue_triage", neighbors)
    labels = ["needs-triage"]
    assignees: list[str] = []
    summary = "Similar issues suggest investigating related regressions."
    return TriageProposal(
        labels=labels,
        assignee_candidates=assignees,
        summary=summary,
        similar=reranked,
    )
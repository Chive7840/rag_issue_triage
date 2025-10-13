"""Sandbox dataset seeding helpers."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any, Iterable, Literal, cast

import asyncpg

from api.services.ingest import normalize_github_issue, normalize_jira_issue, store_issue
from api.utils.logging_utils import get_logger

logger = get_logger("api.services.seeding")

DATA_DIR = Path("db/sandbox/synth_data")
GITHUB_FILE = DATA_DIR / "github_issues.ndjson"
JIRA_FILE = DATA_DIR / "jira_issues.ndjson"

@dataclass(slots=True)
class IssueRecord:
    """Normalized issue persisted in memory for search and triage tests."""
    id: int
    source: Literal["github", "jira"]
    title: str
    body: str
    labels: list[str]
    comment_context: str
    score: float
    payload: Any

@dataclass(slots=True)
class ProposalRecord:
    """Internal representation of a generated triage proposal."""
    proposal_id: int
    issue_id: str
    labels: list[str]
    comment: str | None
    reason: str | None


_issue_cache: dict[int, IssueRecord] = {}
_proposals: dict[str, ProposalRecord] = {}
_proposal_sequence = count(1)

def reset_state() -> None:
    """Reset cached state for test isolation."""
    global _issue_cache, _proposals, _proposal_sequence
    _issue_cache = {}
    _proposals = {}
    _proposal_sequence = count(1)


def _load_seed_file(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)



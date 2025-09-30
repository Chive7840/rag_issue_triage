"""Pydantic schemas for the Issue Triage Copilot API"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional, Sequence

from pydantic import BaseModel, Field, HttpUrl

class IssuePayload(BaseModel):
    source: str
    external_key: str
    title: str
    body: str
    repo: Optional[str] = None
    project: Optional[str] = None
    status: Optional[str] = None
    created_at: datetime
    raw_json: dict[str, Any]

class TriageRequest(BaseModel):
    issue_id: int

class EmbedJob(BaseModel):
    issue_id: int
    force: bool = False

class RetrievalResult(BaseModel):
    issue_id: int
    title: str
    summary: Optional[str] = None
    score: float
    url: Optional[HttpUrl] = None

class TriageProposal(BaseModel):
    labels: List[str]
    assignee_candidates: List[str]
    summary: str
    similar: Sequence[RetrievalResult] = field(default_factory=list)

class ProposalApproval(BaseModel):
    issue_id: int
    labels: List[str]
    assignee: Optional[str] = None
    comment: Optional[str] = None
    source: str = "github"

class SearchResponse(BaseModel):
    query: str
    results: Sequence[RetrievalResult]

class HealthResponse(BaseModel):
    status: str
    details: dict[str, Any] = field(default_factory=dict)
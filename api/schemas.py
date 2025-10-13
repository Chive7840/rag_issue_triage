"""Pydantic schemas for the Issue Triage Copilot API"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence, Tuple
from dataclasses import field
from pydantic import BaseModel, HttpUrl


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
    route: Optional[str] = None
    url: Optional[HttpUrl] = None


class TriageProposal(BaseModel):
    labels: Tuple[str, ...]
    assignee_candidates: Tuple[str, ...]
    summary: str
    similar: Tuple[RetrievalResult, ...] = ()


class ProposalApproval(BaseModel):
    issue_id: int
    labels: list[str]
    assignee: Optional[str] = None
    comment: Optional[str] = None
    source: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    results: Sequence[RetrievalResult]


class HealthResponse(BaseModel):
    status: str
    details: Optional[dict[str, Any]] = None


class IssueRoute(BaseModel):
    route: str


class IssueViewerComment(BaseModel):
    author: Optional[str] = None
    body: str
    body_html: str
    created_at: Optional[datetime] = None


class IssueViewerRecord(BaseModel):
    id: int
    source: str
    route: str
    origin_url: Optional[HttpUrl] = None
    title: str
    body: str
    body_html: str
    repo: Optional[str] = None
    project: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    labels: list[str] = field(default_factory=list)
    created_at: Optional[datetime] = None
    determinism: str
    comments: list[IssueViewerComment] = field(default_factory=list)


class IssueSearchItem(BaseModel):
    id: int
    source: str
    route: str
    origin_url: Optional[HttpUrl] = None
    title: str
    status: Optional[str] = None
    priority: Optional[str] = None
    labels: list[str] = field(default_factory=list)
    repo: Optional[str] = None
    project: Optional[str] = None
    created_at: Optional[datetime] = None


class IssueSearchResponse(BaseModel):
    items: list[IssueSearchItem]

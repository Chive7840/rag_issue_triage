"""Routes exposing the origin-safe issue viewer read APIs."""

from __future__ import annotations

from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from api.schemas import (
    IssueRoute,
    IssueSearchItem,
    IssueSearchResponse,
    IssueViewerRecord,
)
from api.services import retrieve

router = APIRouter(prefix="/api", tags=["viewer"])


async def get_db_pool(request: Request) -> asyncpg.Pool:
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise RuntimeError("Database pool is not configured on the application state")
    return pool


@router.get("/routes", response_model=list[IssueRoute])
async def get_routes(pool: asyncpg.Pool = Depends(get_db_pool)) -> list[IssueRoute]:
    routes = await retrieve.list_canonical_routes(pool)
    return [IssueRoute(route=route) for route in routes]


@router.get("/issues/by-route/{route:path}", response_model=IssueViewerRecord)
async def get_issue_by_route(
        route: str,
        pool: asyncpg.Pool = Depends(get_db_pool),
) -> IssueViewerRecord | JSONResponse:
    record = await retrieve.fetch_issue_by_route(pool, route)
    if record is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": "route not found",
                "hint": "Use /api/routes or /api/issues/search to discover available issues.",
            },
        )
    return IssueViewerRecord.model_validate(record)


@router.get("/issues/search", response_model=IssueSearchResponse)
async def search_issues(
        pool: asyncpg.Pool = Depends(get_db_pool),
        q: str | None = Query(default=None),
        source: list[str] | None = Query(default=None),
        repo: list[str] | None = Query(default=None),
        project: list[str] | None = Query(default=None),
        label: list[str] | None = Query(default=None),
        state: list[str] | None = Query(default=None),
        priority: list[str] | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
) -> IssueSearchResponse:
    filters: dict[str, Any] = {
        "q": q,
        "sources": source or None,
        "repos": repo or None,
        "projects": project or None,
        "labels": label or None,
        "states": state or None,
        "priorities": priority or None,
    }
    results = await retrieve.search_viewer_issues(pool, filters=filters, limit=limit)
    items = [IssueSearchItem.model_validate(item) for item in results]
    return IssueSearchResponse(items=items)

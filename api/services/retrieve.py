"""Retrieval service backed by Postgres + pgvector."""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
import html
import re
from typing import Any
from urllib.parse import urlparse

import asyncpg
import numpy as np

from ..schemas import RetrievalResult
from .embeddings import DEFAULT_MODEL
from api.utils.logging_utils import get_logger, logging_context

logger = get_logger("api.services.retrieve")

_GITHUB_ISSUE_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/issues/(\d+)(?:[?#/].*)?$", re.IGNORECASE)
_JIRA_ISSUE_RE = re.compile(r"^https://([A-Za-z0-9-]+)\.atlassian\.net/browse/([A-Za-z0-9][A-Za-z0-9_-]*-\d+)(?:[?#/].*)?$", re.IGNORECASE)
_URL_RE = re.compile(r"(https?://[^\s<>]+)")


def _as_vector(embedding: np.ndarray | Iterable[float]) -> list[float]:
    array = np.asarray(embedding, dtype=np.float32)
    if array.ndim != 1:
        array = array.reshape(-1)
    return array.tolist()


def _vector_literal(vector: Sequence[float]) -> str:
    """Serialize a vector for pgvector queries.

    asyncpg does not automatically coerce Python sequences to the pgvector type,
    so we emit the JSON representation that pgvector accepts, matching the
    format used when persisting embeddings.

    :param vector:
    :return:
    """

    return json.dumps([float(component) for component in vector], ensure_ascii=False, separators=(",", ":"))


def _vector_sql_literal(vector: Sequence[float]) -> str:
    """Return a SQL literal that casts the vector to the pgvector type."""

    literal = _vector_literal(vector)
    # json.dumps never produces single quotes, but double the character just in case
    # to remain safe when interpolating into SQL.
    escaped = literal.replace("'", "''")
    return f"'{escaped}'::vector"


def _row_value(row: asyncpg.Record, key: str, default: object | None = None) -> object | None:
    """Return a value from an asyncpg.Record or plain mapping without KeyErrors."""

    getter = getattr(row, "get", None)
    if callable(getter):
        try:
            return getter(key, default)     # type: ignore[misc]
        except TypeError:
            # asyncpg.Record.get only accepts (key, default); if we passed
            # incompatible defaults fall back to __getitem__.
            pass
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _resolve_url(row: asyncpg.Record) -> str | None:
    """Best effort construction of an issue URL from a search row."""

    raw = _row_value(row, "raw_json") or {}
    issue_payload = raw.get("issue") if isinstance(raw, dict) else None
    if isinstance(issue_payload, dict):
        html_url = (
            issue_payload.get("html_url")
            or issue_payload.get("url")
            or issue_payload.get("self")
        )
    elif isinstance(raw, dict):
        html_url = raw.get("html_url") or raw.get("self")
    else:
        html_url = None
    if html_url:
        return html_url

    source = str(_row_value(row, "source") or "").lower()
    repo = _row_value(row, "repo")
    project = _row_value(row, "project")
    external_key = _row_value(row, "external_key")
    issue_id = _row_value(row, "id")

    if source == "github" and repo and external_key:
        _, _, maybe_number = str(external_key).partition("#")
        if maybe_number.isdigit():
            return f"https://github.com/{repo}/issues/{maybe_number}"
        if str(issue_id).isdigit():
            return f"https://github.com/{repo}/issues/{issue_id}"

    if project:
        key = external_key or issue_id
        if key is not None:
            return f"https://{project}.atlassian.net/browse/{key}"

    if repo and str(issue_id).isdigit():
        return f"https://github.com/{repo}/issues/{issue_id}"

    return None


def _row_to_result(row: asyncpg.Record, score: float) -> RetrievalResult:
    raw = _ensure_mapping(_row_value(row, "raw_json"))
    route_info = _build_canonical_route(row, raw)
    route = route_info["route"] if route_info else None
    return RetrievalResult(
        issue_id=row["id"],
        title=row["title"],
        score=score,
        route=route,
        url=_resolve_url(row),
    )


async def vector_search(
        pool: asyncpg.Pool,
        embedding: np.ndarray,
        limit: int = 10,
        model: str = DEFAULT_MODEL,
) -> Sequence[RetrievalResult]:
    vector = _as_vector(embedding)
    vector_sql = _vector_sql_literal(vector)
    query = f"""
        SELECT i.id,
               i.title,
               i.source,
               i.external_key,
               i.repo,
               i.project,
               i.raw_json,
               iv.embedding <-> {vector_sql} AS distance
        FROM issue_vectors iv
        JOIN issues i ON i.id = iv.issue_id
        WHERE iv.model = $1
        ORDER BY iv.embedding <-> {vector_sql}
        LIMIT $2
    """
    params: tuple[object, ...] = (model, limit)
    with logging_context(strategy="vector", limit=limit, model=model):
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        logger.info("vector search completed", extra={"context": {"row_count": len(rows)}})
    results: list[RetrievalResult] = []
    for row in rows:
        distance = float(row["distance"])
        score = max(1.0 - max(distance, 0.0), 0.0)
        results.append(_row_to_result(row, score))
    return results


async def hybrid_search(
        pool: asyncpg.Pool,
        embedding: np.ndarray | Iterable[float],
        query: str,
        limit: int = 10,
        alpha: float = 0.5,
        model: str = DEFAULT_MODEL,
) -> Sequence[RetrievalResult]:
    vector = _as_vector(embedding)
    vector_sql = _vector_sql_literal(vector)
    query_text = f"""
        WITH vector_candidates AS (
            SELECT iv.issue_id,
                   1 / (1 + (iv.embedding <-> {vector_sql})) AS vector_score
            FROM issue_vectors iv
            WHERE iv.model = $4
            ORDER BY iv.embedding <-> {vector_sql}
            LIMIT $1
        ),
        text_candidates AS (
            SELECT i.id,
                   ts_rank_cd(search_vector, plainto_tsquery('english', $2)) AS text_score
            FROM issues i
            WHERE search_vector @@ plainto_tsquery('english', $2)
            ORDER BY text_score DESC
            LIMIT $1
        )
        SELECT i.id,
               i.title,
               i.source,
               i.external_key,
               i.repo,
               i.project,
               i.raw_json,
               COALESCE(vc.vector_score, 0) AS vector_score,
               COALESCE(tc.text_score, 0) AS text_score
        FROM issues i
        LEFT JOIN vector_candidates vc ON vc.issue_id = i.id
        LEFT JOIN text_candidates tc on tc.id = i.id
        WHERE vc.issue_id IS NOT NULL OR tc.id IS NOT NULL
        ORDER BY (COALESCE(vc.vector_score, 0) * $3 + COALESCE(tc.text_score, 0) * (1 - $3)) DESC
        LIMIT $1
    """
    params: tuple[object, ...] = (limit, query, alpha, model)
    with logging_context(strategy="hybrid", limit=limit, model=model, alpha=alpha):
        async with pool.acquire() as conn:
            rows = await conn.fetch(query_text, *params)
        logger.info("Hybrid search completed", extra={"context": {"row_count": len(rows)}})
    results: list[RetrievalResult] = []
    for row in rows:
        vector_score = float(row["vector_score"])
        text_score = float(row["text_score"])
        blended = vector_score * alpha + text_score * (1 - alpha)
        results.append(_row_to_result(row, blended))
    return results


def _ensure_mapping(value: object | None) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, Mapping):
            return parsed
    return {}


def _github_repo_parts(repo_value: object | None, raw: Mapping[str, Any]) -> tuple[str, str]:
    if isinstance(repo_value, str) and repo_value:
        if "/" in repo_value:
            owner, repo = repo_value.split("/", 1)
            return owner, repo
        return "sandbox", repo_value
    repo_hint = None
    repository = raw.get("repository")
    if isinstance(repository, Mapping):
        repo_hint = repository.get("full_name") or repository.get("name")
    if isinstance(repo_hint, str) and repo_hint:
        if "/" in repo_hint:
            owner, repo = repo_hint.split("/", 1)
            return owner, repo
        return "sandbox", repo_hint
    payload_repo = raw.get("repo")
    if isinstance(payload_repo, str) and payload_repo:
        if "/" in payload_repo:
            owner, repo = payload_repo.split("/", 1)
            return owner, repo
        return "sandbox", payload_repo
    return "sandbox", "unknown"


def _issue_number_from_row(row: Mapping[str, Any], raw: Mapping[str, Any]) -> str | None:
    external_key = _row_value(row, "external_key")
    if isinstance(external_key, str) and external_key:
        _, sep, tail = external_key.rpartition("#")
        if sep and tail.strip():
            digits = tail.strip()
            if digits.isdigit():
                return digits
    issue_payload = raw.get("issue") if isinstance(raw, Mapping) else None
    if isinstance(issue_payload, Mapping):
        number = issue_payload.get("number") or issue_payload.get("id")
    else:
        number = raw.get("number")
    if isinstance(number, int):
        return str(number)
    if isinstance(number, str) and number.isdigit():
        return number
    return None


def _jira_site(raw: Mapping[str, Any]) -> str:
    candidates: list[object] = []
    issue_payload = raw.get("issue") if isinstance(raw, Mapping) else None
    if isinstance(issue_payload, Mapping):
        candidates.extend([
            issue_payload.get("self"),
            issue_payload.get("url"),
        ])
        fields = issue_payload.get("fields")
        if isinstance(fields, Mapping):
            candidates.append(fields.get("self"))
    candidates.append(raw.get("self"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            parsed = urlparse(candidate)
            host = parsed.hostname or ""
            if host:
                host = host.split(":", 1)[0]
                if host.endswith(".atlassian.net"):
                    return host.split(".")[0]
                return host.split(".")[0]
    fallback = raw.get("site")
    if isinstance(fallback, str) and fallback:
        return fallback
    return "sandbox"


def _build_canonical_route(row: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, str] | None:
    source = str(_row_value(row, "source") or "").lower()
    if source == "github":
        owner, repo = _github_repo_parts(_row_value(row, "repo"), raw)
        number = _issue_number_from_row(row, raw)
        if not number:
            return None
        route = f"/gh/{owner}/{repo}/issues/{number}"
        return {
            "source": "github",
            "route": route,
            "owner": owner,
            "repo": repo,
            "number": number,
        }
    if source == "jira":
        key_raw = _row_value(row, "external_key")
        if not key_raw:
            return None
        key = str(key_raw)
        project_value = _row_value(row, "project")
        project = str(project_value) if project_value else key.split("-", 1)[0]
        site = _jira_site(raw)
        route = f"/jira/{site}/{project}/{key}"
        return {
            "source": "jira",
            "route": route,
            "project": project,
            "site": site,
            "key": key,
        }
    return None


def _build_origin_url(route_info: dict[str, str] | None) -> str | None:
    if not route_info:
        return None
    if route_info.get("source") == "github":
        owner = route_info.get("owner") or "sandbox"
        repo = route_info.get("repo") or "unknown"
        number = route_info.get("number") or "0"
        return f"https://github.com/{owner}/{repo}/issues/{number}"
    if route_info.get("source") == "jira":
        site = route_info.get("site") or "sandbox"
        key = route_info.get("key") or "ISSUE-0"
        return f"https://{site}.atlassian.net/browse/{key}"
    return None


def _rewrite_url(url: str) -> tuple[str, bool]:
    if not url:
        return url, False
    github = _GITHUB_ISSUE_RE.match(url)
    if github:
        owner, repo, number = github.groups()
        return f"/gh/{owner}/{repo}/issues/{number}", True
    jira = _JIRA_ISSUE_RE.match(url)
    if jira:
        site, key = jira.groups()
        project = key.split("-", 1)[0]
        return f"/jira/{site}/{project}/{key}", True
    return url, False


def _linkify_text(text: str) -> str:
    if not text:
        return ""
    parts: list[str] = []
    last = 0
    for match in _URL_RE.finditer(text):
        start, end = match.span()
        parts.append(html.escape(text[last:start]))
        url = match.group(1)
        trimmed = url.rstrip(".,);")
        suffix = url[len(trimmed):]
        href, is_internal = _rewrite_url(trimmed)
        rel_attr = "" if is_internal else " rel=\"nofollow noopener noreferrer\""
        parts.append(
            f"<a href=\"{html.escape(href)}\"{rel_attr}>{html.escape(trimmed)}</a>"
        )
        if suffix:
            parts.append(html.escape(suffix))
        last = end
    parts.append(html.escape(text[last:]))
    return "".join(parts).replace("\n", "<br />\n")


def _render_text_block(text: str) -> str:
    if not text:
        return ""
    paragraphs: list[str] = []
    buffer: list[str] = []
    for line in text.splitlines():
        if line.strip():
            buffer.append(line)
        else:
            if buffer:
                paragraphs.append("\n".join(buffer))
                buffer = []
    if buffer:
        paragraphs.append("\n".join(buffer))
    if not paragraphs:
        paragraphs.append("")
    rendered: list[str] = []
    for paragraph in paragraphs:
        rendered.append(f"<p>{_linkify_text(paragraph)}</p>")
    return "".join(rendered)


def _collect_labels(row: Mapping[str, Any], raw: Mapping[str, Any]) -> list[str]:
    labels: set[str] = set()
    aggregated = _row_value(row, "labels")
    if isinstance(aggregated, (list, tuple)):
        for label in aggregated:
            if isinstance(label, str) and label.strip():
                labels.add(label.strip())
    raw_labels = raw.get("labels")
    if raw_labels is None and isinstance(raw.get("issue"), Mapping):
        raw_labels = raw["issue"].get("labels")
    if isinstance(raw_labels, list):
        for item in raw_labels:
            if isinstance(item, Mapping):
                name = item.get("name") or item.get("label")
            else:
                name = item
            if isinstance(name, str) and name.strip():
                labels.add(name.strip())
    return sorted(labels)


def _extract_priority(raw: Mapping[str, Any]) -> str | None:
    priority = raw.get("priority")
    if isinstance(priority, Mapping):
        name = priority.get("name") or priority.get("value")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(priority, str) and priority.strip():
        return priority.strip()
    issue_payload = raw.get("issue") if isinstance(raw, Mapping) else None
    if isinstance(issue_payload, Mapping):
        fields = issue_payload.get("fields")
        if isinstance(fields, Mapping):
            priority_field = fields.get("priority")
            if isinstance(priority_field, Mapping):
                value = priority_field.get("name") or priority_field.get("value")
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _parse_datetime(value: object | None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        normalized = value.replace("Z", "+00:00").replace("z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
    return None


def _extract_comments(row: Mapping[str, Any], raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    candidate_lists: list[object] = []
    candidate_lists.append(raw.get("comments"))
    issue_payload = raw.get("issue") if isinstance(raw, Mapping) else None
    if isinstance(issue_payload, Mapping):
        candidate_lists.append(issue_payload.get("comments"))
        fields = issue_payload.get("fields")
        if isinstance(fields, Mapping):
            candidate_lists.append(fields.get("comment"))
    for candidate in candidate_lists:
        if isinstance(candidate, list) and candidate:
            source_list = candidate
            break
    else:
        source_list = []
    for item in source_list:
        if not isinstance(item, Mapping):
            continue
        body = str(item.get("body") or "")
        author_obj = item.get("author") or item.get("user")
        if isinstance(author_obj, Mapping):
            author = author_obj.get("displayName") or author_obj.get("login") or author_obj.get("name")
        elif isinstance(author_obj, str):
            author = author_obj
        else:
            author = None
        created = item.get("created") or item.get("at") or item.get("updated")
        comments.append(
            {
                "author": str(author) if author else None,
                "body": body,
                "body_html": _render_text_block(body),
                "created_at": _parse_datetime(created),
            }
        )
    return comments


def _determinism_banner(source: str, raw: Mapping[str, Any]) -> str:
    parts = ["Synthetic."]
    seed = raw.get("seed")
    generation_obj = raw.get("generation")
    generation = generation_obj if isinstance(generation_obj, Mapping) else None
    if seed is None and isinstance(generation, Mapping):
        seed = generation.get("seed")
    if isinstance(seed, (int, float, str)) and str(seed):
        parts.append(f"Seed: {seed}.")
    gen_time = raw.get("generatedAt")
    if gen_time is None and isinstance(generation, Mapping):
        gen_time = generation.get("time") or generation.get("timestamp")
    if gen_time is None:
        gen_time = raw.get("generation_time")
    if gen_time is None:
        gen_time = raw.get("createdAt")
    if isinstance(gen_time, (int, float, str)) and str(gen_time):
        parts.append(f"Generated: {gen_time}.")
    parts.append(f"Source: {source}.")
    return " ".join(parts)


def _project_issue_record(row: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = _ensure_mapping(_row_value(row, "raw_json"))
    route_info = _build_canonical_route(row, raw)
    if not route_info:
        return None
    labels = _collect_labels(row, raw)
    priority = _extract_priority(raw)
    determinism = _determinism_banner(str(route_info.get("source", "")), raw)
    body = str(_row_value(row, "body") or "")
    comments = _extract_comments(row, raw)
    return {
        "id": int(_row_value(row, "id")),
        "source": route_info["source"],
        "route": route_info["route"],
        "origin_url": _build_origin_url(route_info),
        "title": str(_row_value(row, "title") or ""),
        "body": body,
        "body_html": _render_text_block(body),
        "repo": _row_value(row, "repo"),
        "project": _row_value(row, "project"),
        "status": _row_value(row, "status"),
        "priority": priority,
        "labels": labels,
        "created_at": _row_value(row, "created_at"),
        "determinism": determinism,
        "comments": comments,
    }


def _project_issue_summary(row: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = _ensure_mapping(_row_value(row, "raw_json"))
    route_info = _build_canonical_route(row, raw)
    if not route_info:
        return None
    return {
        "id": int(_row_value(row, "id")),
        "source": route_info["source"],
        "route": route_info["route"],
        "origin_url": _build_origin_url(route_info),
        "title": str(_row_value(row, "title") or ""),
        "status": _row_value(row, "status"),
        "priority": _extract_priority(raw),
        "labels": _collect_labels(row, raw),
        "repo": _row_value(row, "repo"),
        "project": _row_value(row, "project"),
        "created_at": _row_value(row, "created_at"),
    }


async def list_canonical_routes(pool: asyncpg.Pool) -> list[str]:
    query = """
        SELECT id,
               source,
               external_key,
               repo,
               project,
               raw_json
        FROM issues
        ORDER BY id ASC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query)
    routes: list[str] = []
    for row in rows:
        raw = _ensure_mapping(_row_value(row, "raw_json"))
        route_info = _build_canonical_route(row, raw)
        if route_info:
            routes.append(route_info["route"])
    # Preserve order while removing duplicates
    return list(dict.fromkeys(routes))


def _parse_route(route: str) -> dict[str, Any] | None:
    if not route:
        return None
    normalized = route if route.startswith("/") else f"/{route}"
    parts = [segment for segment in normalized.split("/") if segment]
    if len(parts) >= 5 and parts[0] == "gh" and parts[3] == "issues":
        owner = parts[1]
        repo = parts[2]
        number = parts[4]
        repo_full = f"{owner}/{repo}"
        return {
            "source": "github",
            "owner": owner,
            "repo": repo,
            "number": number,
            "repo_candidates": [repo_full, repo],
        }
    if len(parts) >= 4 and parts[0] == "jira":
        site = parts[1]
        project = parts[2]
        key = parts[3]
        return {
            "source": "jira",
            "site": site,
            "project": project,
            "key": key,
        }
    return None


async def fetch_issue_by_route(pool: asyncpg.Pool, route: str) -> dict[str, Any] | None:
    parsed = _parse_route(route)
    if not parsed:
        return None
    source = parsed["source"]
    params: list[Any] = [source]
    if source == "github":
        number = parsed["number"]
        repo_candidates = parsed["repo_candidates"]
        external_keys = [f"{candidate}#{number}" for candidate in repo_candidates]
        params.append(external_keys)
        query = """
            SELECT i.id,
                   i.source,
                   i.external_key,
                   i.title,
                   i.body,
                   i.repo,
                   i.project,
                   i.status,
                   i.created_at,
                   i.raw_json,
                   COALESCE(array_agg(DISTINCT l.label) FILTER (WHERE l.label IS NOT NULL), '{{}}') AS labels
            FROM issues i
            LEFT JOIN labels l ON l.issue_id = i.id
            WHERE i.source = $1
              AND i.external_key = ANY($2::text[])
            GROUP BY i.id
            ORDER BY i.id ASC
            LIMIT 1
        """
    else:  # jira
        key = parsed["key"]
        params.append(key)
        query = """
            SELECT i.id,
                   i.source,
                   i.external_key,
                   i.title,
                   i.body,
                   i.repo,
                   i.project,
                   i.status,
                   i.created_at,
                   i.raw_json,
                   COALESCE(array_agg(DISTINCT l.label) FILTER (WHERE l.label IS NOT NULL), '{{}}') AS labels
            FROM issues i
            LEFT JOIN labels l ON l.issue_id = i.id
            WHERE i.source = $1
              AND i.external_key = $2
            GROUP BY i.id
            ORDER BY i.id ASC
            LIMIT 1
        """
    async with pool.acquire() as conn:
        record = await conn.fetchrow(query, *params)
    if not record:
        return None
    projected = _project_issue_record(record)
    if projected is None:
        return None
    return projected


async def search_viewer_issues(
        pool: asyncpg.Pool,
        *,
        filters: Mapping[str, Any],
        limit: int = 50,
) -> list[dict[str, Any]]:
    where_clauses: list[str] = []
    params: list[Any] = []
    idx = 1

    q = filters.get("q")
    if q:
        where_clauses.append(f"i.search_vector @@ plainto_tsquery('english', ${idx})")
        params.append(q)
        idx += 1

    sources = filters.get("sources")
    if sources:
        where_clauses.append(f"i.source = ANY(${idx})")
        params.append(list(sources))
        idx += 1

    repos = filters.get("repos")
    if repos:
        where_clauses.append(f"i.repo = ANY(${idx})")
        params.append(list(repos))
        idx += 1

    projects = filters.get("projects")
    if projects:
        where_clauses.append(f"i.project = ANY(${idx})")
        params.append(list(projects))
        idx += 1

    states = filters.get("states")
    if states:
        where_clauses.append(f"i.status = ANY(${idx})")
        params.append(list(states))
        idx += 1

    priorities = filters.get("priorities")
    if priorities:
        where_clauses.append(f"COALESCE(i.raw_json->>'priority', '') = ANY(${idx})")
        params.append(list(priorities))
        idx += 1

    labels = filters.get("labels")
    label_clause = ""
    if labels:
        label_clause = f"AND l.label = ANY(${idx})"
        params.append(list(labels))
        idx += 1

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    query = f"""
        WITH base AS (
            SELECT i.id,
                   i.source,
                   i.external_key,
                   i.title,
                   i.body,
                   i.repo,
                   i.project,
                   i.status,
                   i.created_at,
                   i.raw_json
            FROM issues i
            {where_sql}
            ORDER BY i.created_at DESC, i.id DESC
            LIMIT ${idx}
        )
        SELECT b.id,
               b.source,
               b.external_key,
               b.title,
               b.body,
               b.repo,
               b.project,
               b.status,
               b.created_at,
               b.raw_json,
               COALESCE(array_agg(DISTINCT l.label) FILTER (WHERE l.label IS NOT NULL), '{{}}') AS labels
        FROM base b
        LEFT JOIN labels l ON l.issue_id = b.id {label_clause}
        GROUP BY b.id, b.source, b.external_key, b.title, b.body, b.repo, b.project, b.status, b.created_at, b.raw_json
        ORDER BY b.created_at DESC, b.id DESC
    """
    params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    projected: list[dict[str, Any]] = []
    for row in rows:
        summary = _project_issue_summary(row)
        if summary:
            projected.append(summary)
    return projected

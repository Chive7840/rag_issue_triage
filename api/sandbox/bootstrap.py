"""Bootstrap helpers for loading deterministic sandbox data."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import asyncpg

from api.schemas import IssuePayload
from api.services import embeddings
from api.utils.logging_utils import get_logger, logging_context

logger = get_logger("api.sandbox.bootstrap")

DATA_FILES = {
    "github": "github_issues.ndjson",
    "jira": "jira_issues.ndjson",
}

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "db" / "sandbox"
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/triage"
INIT_SQL_PATH = Path(__file__).resolve().parents[2] / "db" / "init.sql"

async def ensure_vector_extension(pool: asyncpg.Pool) -> None:
    """Ensure the pgvector extension is available in the sandbox database."""

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )
        if exists:
            return

        logger.info("Enabling pgvector extension in sandbox database")
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


def _resolve_dataset_path(path: Path) -> Path | None:
    if path.exists():
        return path
    gz_path = path.with_suffix(path.suffix + ".gz")
    if gz_path.exists():
        return gz_path
    return None


def _iter_records(path: Path) -> Iterator[dict[str, object]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _parse_timestamp(raw: object) -> datetime:
    if isinstance(raw, datetime):
        value = raw
    else:
        text = str(raw or "")
        if not text:
            return datetime.now(timezone.utc)
        normalized = text.replace("Z", "+00:00").replace("z", "+00:00")
        try:
            value = datetime.fromisoformat(normalized)
        except ValueError:
            return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _coerce_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _serialize_embedding(vector: Iterable[float]) -> str:
    return json.dumps([float(component) for component in vector], ensure_ascii=False, separators=(",",":"))


async def _vector_column_dimension(
        conn: asyncpg.Connection,
        *,
        table: str,
        column: str,
) -> int | None:
    """Return the declared dimension for a pgvector column when available."""

    atttypmod = await conn.fetchval(
        """
        SELECT atttypmod
        FROM pg_attribute
        WHERE attrelid = to_regclass($1)::oid
          AND attname = $2
          AND NOT attisdropped
        """,
        table,
        column,
    )
    if atttypmod is None or atttypmod <= 4:
        return None
    # pgvector stores the typmod as dimension + VARHDRSZ (4).
    return int(atttypmod)


def _current_status(record: dict[str, object], *, flavor: str) -> str:
    transitions = record.get("transitions") if isinstance(record, dict) else None
    if isinstance(transitions, list) and transitions:
        last = transitions[-1]
        if isinstance(last, dict):
            status = last.get("to")
            if isinstance(status, str) and status:
                return status
    if flavor == "github":
        return "Open"
    return "To Do"


def _make_payload(record: dict[str, object], *, flavor: str) -> IssuePayload:
    created_at = _parse_timestamp(record.get("createdAt")) if isinstance(record, dict) else datetime.now(timezone.utc)
    title = _coerce_text(record.get("title") if isinstance(record, dict) else "")
    body = _coerce_text(record.get("body") if isinstance(record, dict) else "")
    if flavor == "github":
        repo = record.get("repo") if isinstance(record, dict) else None
        number = record.get("number") if isinstance(record, dict) else None
        if isinstance(number, int):
            external_key = f"{repo or 'sandbox'}#{number}"
        else:
            external_key = str(record.get("id", "github")) if isinstance(record, dict) else "github"
        project = None
    else:
        repo = None
        project = record.get("projectKey") if isinstance(record, dict) else None
        number = record.get("number") if isinstance(record, dict) else None
        if project and isinstance(number, int):
            external_key = f"{project}-{number}"
        else:
            external_key = str(record.get("id", "jira")) if isinstance(record, dict) else "jira"
    status = _current_status(record if isinstance(record, dict) else {}, flavor=flavor)
    payload = IssuePayload(
        source=flavor,
        external_key=external_key,
        title=title,
        body=body or "",
        repo=repo,
        project=project,
        status=status,
        created_at=created_at,
        raw_json=record if isinstance(record, dict) else {},
    )
    return payload


async def _upsert_issue(conn: asyncpg.Connection, payload: IssuePayload) -> int:
    created_at = payload.created_at
    if isinstance(created_at, datetime) and created_at.tzinfo is not None:
        created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)

    record = await conn.fetchrow(
        """
        INSERT INTO issues (
            source,
            external_key,
            title,
            body,
            repo,
            project,
            status,
            created_at,
            raw_json
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (source, external_key) DO UPDATE SET
            title = EXCLUDED.title,
            body = EXCLUDED.body,
            repo = EXCLUDED.repo,
            project = EXCLUDED.project,
            status = EXCLUDED.status,
            created_at = EXCLUDED.created_at,
            raw_json = EXCLUDED.raw_json
        RETURNING id
        """,
        payload.source,
        payload.external_key,
        payload.title,
        payload.body,
        payload.repo,
        payload.project,
        payload.status,
        created_at,
        json.dumps(payload.raw_json, ensure_ascii=False),
    )
    if record is None:
        raise RuntimeError("Failed to upsert issue payload")
    return int(record["id"])

async def _replace_labels(conn: asyncpg.Connection, issue_id: int, labels: Iterable[object], source: str) -> None:
    cleaned: list[str] = []
    for label in labels:
        text = _coerce_text(label).strip()
        if text:
            cleaned.append(text)
    await conn.execute("DELETE FROM labels WHERE issue_id = $1", issue_id)
    if not cleaned:
        return
    await conn.executemany(
        "INSERT INTO labels (issue_id, label, source) VALUES ($1, $2, $3)",
        [(issue_id, label, source) for label in cleaned],
    )

async def _ensure_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT to_regclass('public.issues')")
        if exists:
            return
        if not INIT_SQL_PATH.exists():
            raise FileNotFoundError(f"Database schema file not found at {INIT_SQL_PATH}")
        logger.info("Applying sandbox database schema", extra={"context": {"path": str(INIT_SQL_PATH)}})
        script = INIT_SQL_PATH.read_text(encoding="utf-8")
        statements = [chunk.strip() for chunk in script.split(";") if chunk.strip()]
        for statement in statements:
            await conn.execute(statement)


async def ensure_sample_data(
        pool: asyncpg.Pool,
        *,
        data_dir: Path | str | None = None,
        force: bool = False,
) -> int:
    """Load sandbox issues when the database is empty."""

    await ensure_vector_extension(pool)

    base_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    if not base_dir.exists():
        logger.warning("Sandbox data directory not found", extra={"context": {"path": str(base_dir)}})
        return 0

    if force:
        async with pool.acquire() as conn:
            with logging_context(operation="truncate_sandbox"):
                logger.info("Clearing sandbox tables")
            await conn.execute("TRUNCATE TABLE issues RESTART IDENTITY CASCADE")

    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT COUNT(*) FROM issues")
    if existing and not force:
        logger.info("Issues already present; skipping sample load", extra={"context": {"count":int(existing)}})
        return 0

    inserted = 0
    for flavor, filename in DATA_FILES.items():
        dataset = _resolve_dataset_path(base_dir / filename)
        if dataset is None:
            logger.warning("Sandbox dataset missing", extra={"context": {"flavor": flavor, "filename": filename}})
            continue
        records = list(_iter_records(dataset))
        if not records:
            continue
        with logging_context(flavor=flavor, records=len(records)):
            logger.info("Loading sandbox dataset")
        async with pool.acquire() as conn:
            async with conn.transaction():
                for record in records:
                    payload = _make_payload(record, flavor=flavor)
                    issue_id = await _upsert_issue(conn, payload)
                    await _replace_labels(
                        conn,
                        issue_id,
                        record.get("labels", []) if isinstance(record, dict) else [],
                        flavor
                    )
                    inserted += 1
    logger.info("Sandbox data load complete", extra={"context": {"inserted": inserted}})
    return inserted


def _chunk(sequence: Sequence[asyncpg.Record], size: int) -> Iterator[Sequence[asyncpg.Record]]:
    for start in range(0, len(sequence), size):
        yield sequence[start : start + size]


async def ensure_embeddings(
        pool: asyncpg.Pool,
        *,
        model: str = embeddings.DEFAULT_MODEL,
        batch_size: int = 32,
        force: bool = False,
) -> int:
    """Compute embeddings for all issues if they are missing."""

    await ensure_vector_extension(pool)

    vector_dimension: int | None = None
    async with pool.acquire() as conn:
        total_issues = await conn.fetchval("SELECT COUNT(*) FROM issues")
        if not total_issues:
            logger.info("No issues available for embedding")
            return 0
        if not force:
            missing = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM issues i 
                LEFT JOIN issue_vectors v on v.issue_id = i.id
                WHERE v.issue_id IS NULL
                """,
            )
            if missing == 0 and await conn.fetchval("SELECT COUNT(*) FROM issue_vectors"):
                logger.info("Embeddings already populated; skipping")
                return 0
        vector_dimension = await _vector_column_dimension(
            conn,
            table="issue_vectors",
            column="embedding",
        )

    expected_dimension = embeddings.get_model(model).get_sentence_embedding_dimension()
    if vector_dimension is not None and vector_dimension != expected_dimension:
        raise RuntimeError(
            "issue_vectors.embedding expects {declared} dimensions but the '{model}' model produces {actual}."
            "Adjust the sandbox schema or use a compatible model.".format(
                declared=vector_dimension,
                model=model,
                actual=expected_dimension,
            )
        )

    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, title, body FROM issues ORDER BY id")

    processed = 0
    for chunk in _chunk(rows, batch_size):
        texts = [f"{_coerce_text(row['title'])}\n\n{_coerce_text(row['body'])}".strip() for row in chunk]
        vectors = embeddings.encode_texts(texts, model_name=model)
        if len(vectors) != len(chunk):
            raise RuntimeError("Embedding count mismatch during sandbox bootstrap")
        async with pool.acquire() as conn:
            async with conn.transaction():
                for row, vector in zip(chunk, vectors):
                    embedding_arg = _serialize_embedding(vector)
                    await conn.execute(
                        """
                        INSERT INTO issue_vectors (issue_id, embedding, model, updated_at)
                        VALUES ($1, $2, $3, NOW())
                        ON CONFLICT (issue_id) DO UPDATE SET
                            embedding = EXCLUDED.embedding,
                            model = EXCLUDED.model,
                            updated_at = NOW()
                        """,
                        row["id"],
                        embedding_arg,
                        model,
                    )
        processed += len(chunk)
    logger.info("Embedded sandbox issues", extra={"context": {"count": processed, "model": model}})
    return processed


@dataclass
class CommandResult:
    exit_code: int = 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sandbox bootstrap utilities")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        help="PostgreSQL connection string",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    data_cmd = sub.add_parser("load-data", help="Load sandbox issues into the database")
    data_cmd.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    data_cmd.add_argument("--force", action="store_true", help="Truncate tables before loading data")

    embed_cmd = sub.add_parser("load-embeddings", help="Compute embeddings for sandbox issues")
    embed_cmd.add_argument("--model", default=embeddings.DEFAULT_MODEL)
    embed_cmd.add_argument("--batch-size", type=int, default=32)
    embed_cmd.add_argument("--force", action="store_true", help="Recompute embeddings even if present")

    boot_cmd = sub.add_parser("bootstrap", help="Load data and embeddings in a single command")
    boot_cmd.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    boot_cmd.add_argument("--model", default=embeddings.DEFAULT_MODEL)
    boot_cmd.add_argument("--batch-size", type=int, default=32)
    boot_cmd.add_argument("--force", action="store_true", help="Force reload of data and embeddings")

    return parser


async def _dispatch(args: argparse.Namespace) -> CommandResult:
    pool = await asyncpg.create_pool(dsn=args.database_url)
    try:
        await _ensure_schema(pool)
        if args.command == "load-data":
            await ensure_sample_data(pool, data_dir=Path(args.data_dir), force=args.force)
        elif args.command == "load-embeddings":
            await ensure_embeddings(
                pool,
                model=args.model,
                batch_size=args.batch_size,
                force=args.force,
            )
        elif args.command == "bootstrap":
            await ensure_sample_data(pool, data_dir=Path(args.data_dir), force=args.force)
            await ensure_embeddings(
                pool,
                model=args.model,
                batch_size=args.batch_size,
                force=True if args.force else False,
            )
        else:
            return CommandResult(exit_code=1)
        return CommandResult(exit_code=0)
    finally:
        await pool.close()


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) is None:
        args.command = "bootstrap"
        # Mirror defaults from the bootstrap subcommand so invoking the module
        # without arguments remains deterministic for local sandboxes
        args.data_dir = str(DEFAULT_DATA_DIR)
        args.model = embeddings.DEFAULT_MODEL
        args.batch_size = 32
        args.force = False
    try:
        result = asyncio.run(_dispatch(args))
    except KeyboardInterrupt:
        return 130
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(run_cli())
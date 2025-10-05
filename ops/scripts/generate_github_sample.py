"""Generate deterministic GitHub-like issues for the sandbox dataset.

The portfolio sandbox needs expressive fixtures (labels, comments, events, duplicate detection, etc.)
The generation logic is deterministic so the committed dataset can be recreated exactly when the script is executed.
To scale the payload up or down while keeping the template coverage use the ``--multiplier``.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from faker import Faker


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT / "db" / "sandbox" / "github_issues.jsonl"
DEFAULT_MULTIPLIER = 3
CYCLE_SPACING_DAYS = 21

faker = Faker()
RANDOM_SEED = 20240417
random.seed(RANDOM_SEED)
faker.seed_instance(RANDOM_SEED)


TEAM_MEMBERS = [
    "aria.dev",
    "mike.ops",
    "chen.data",
    "samira.qa",
    "luis.platform",
    "triage-bot",
]


LABEL_COLORS = {
    "bug": "d73a4a",
    "high priority": "b60205",
    "triage": "fbca04",
    "documentation": "0075ca",
    "enhancement": "a2eeef",
    "analytics": "d876e3",
    "ux": "0052cc",
    "dependencies": "0366d6",
}

REPOSITORIES = {
    "orion-notify": {
        "name": "Orion Notify",
        "description": "Async notification dispatcher that fans out alerts to emai, sms, and PagerDuty.",
        "languages": ["Python", "TypeScript"],
        "topics": ["notifications", "observability", "workers"],
    },
    "atlas-deployer": {
        "name": "Atlas Deployer",
        "description": "Infrastructure-as-code orchestrator used to promote platform services.",
        "languages": ["Python", "HCL"],
        "topics": ["infrastructure", "devops", "automation"],
    },
    "voyager-analytics": {
        "name": "Voyager Analytics",
        "description": "Customer-facing analytics with configurable dashboards and anomaly detection.",
        "languages": ["TypeScript", "SQL"],
        "topics": ["analytics", "dashboards", "product"],
    },
}

@dataclass(frozen=True)
class IssueTemplate:
    repo: str
    title: str
    body: str
    labels: List[str]
    state: str
    kind: str = "issue"     # either "issue" or "pull_request"
    comment_count: int = 1
    duplicate_group: Optional[str] = None
    events: Optional[List[str]] = None
    assignees: Optional[List[str]] = None

PAGERDUTY_DUPLICATE_BODY = (
    "PagerDuty sync job fails for members who opted out of SMS."
    "The nightly worker throws a KeyError when it attempts to map the opt-out "
    "status, so alerts never reach the on-call engineer."
)

ISSUE_LIBRARY: List[IssueTemplate] = [
    IssueTemplate(
        repo="orion-notify",
        title="PagerDuty sync fails when users opt-out of SMS.",
        body=PAGERDUTY_DUPLICATE_BODY,
        labels=["bug", "high priority"],
        state="open",
        comment_count=2,
        duplicate_group="pagerduty-sync",
        events=["labeled", "assigned"],
        assignees=["aria.dev"],
    ),
    IssueTemplate(
        repo="orion-notify",
        title="PagerDuty sync regression after timezone rollout",
        body=PAGERDUTY_DUPLICATE_BODY,
        labels=["bug", "triage"],
        state="closed",
        comment_count=1,
        duplicate_group="pagerduty-sync",
        events=["labeled"],
    ),
    IssueTemplate(
        repo="orion-notify",
        title="Document retry semantics for webhook deliveries.",
        body=(
            "Support has asked for clearer documentation on how webhook retries are scheduled."
            "We should include examples for exponential backoff and manual redrive."
        ),
        labels=["documentation"],
        state="closed",
        comment_count=1,
        events=["labeled", "closed"],
        assignees=["samira.qa"],
    ),
    IssueTemplate(
        repo="atlas-deployer",
        title="Promote release pipeline: Terraform state drift",
        body=(
            "Terraform plan detects drift on the shared VPC when running the promote pipeline. "
            "It appears service accounts created by SSO aren't being imported before apply."
        ),
        labels=["bug", "triage"],
        state="open",
        comment_count=3,
        events=["labeled", "commented"],
        assignees=["mike.ops"],
    ),
    IssueTemplate(
        repo="atlas-deployer",
        title="Refactor deploy UI to highlight manual approvals",
        body=(
            "Product wants the deploy dashboard to display pending manual approvals more prominently. "
            "Propose adding a side panel with the change request metadata and action buttons."
        ),
        labels=["enhancement", "ux"],
        state="open",
        comment_count=2,
        events=["labeled"],
    ),
    IssueTemplate(
        repo="voyager-analytics",
        title="Add percentile aggregations to custom dashboards",
        body=(
            "Customers building reliability dashboards need P95 and P99 metrics. "
            "Expose percentile aggregations for numerical columns in chart configs."
        ),
        labels=["enhancement", "analytics"],
        state="open",
        comment_count=2,
        events=["labeled", "commented"],
        kind="pull_request",
        assignees=["chen.data"],
    ),
    IssueTemplate(
        repo="voyager-analytics",
        title="Bump Postgres client to fix connection leak",
        body=(
            "Upgrade psycopg adapter to 3.1.19. The current version leaves idle transactions "
            "when the dashboard worker restarts, exhausting the connection pool."
        ),
        labels=["dependencies", "bug"],
        state="closed",
        comment_count=1,
        events=["labeled", "closed"],
        kind="pull_request",
    ),
]

def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "z")

def choose_user(exclude: Optional[Iterable[str]] = None) -> str:
    population = [member for member in TEAM_MEMBERS if member not in (exclude or [])]
    return random.choice(population)

def make_comment(author: str, created_at: datetime) -> dict:
    return {
        "author": author,
        "body": faker.paragraph(nb_sentences=3),
        "created_at": iso(created_at),
    }

def label_payload(label: str) -> dict:
    return {
        "name": label,
        "color": LABEL_COLORS.get(label, "ededed"),
    }

def generate_events(template: IssueTemplate, created_at: datetime, updated_at: datetime) -> List[dict]:
    events: List[dict] = []
    cursor = created_at
    for event in template.events or []:
        cursor += timedelta(minutes=random.randint(5, 90))
        payload = {
            "type": event,
            "actor": choose_user(),
            "created_at": iso(cursor),
        }
        if event == "labeled" and template.labels:
            payload["label"] = random.choice(template.labels)
        if event == "assigned" and template.assignees:
            payload["assignee"] = random.choice(template.assignees)
        if event == "closed":
            payload["state"] = "closed"
            payload["created_at"] = iso(updated_at)
        events.append(payload)
    return events

def generate_pull_request(template: IssueTemplate, created_at: datetime, updated_at: datetime) -> Optional[dict]:
    if template.kind != "pull_request":
        return None
    merged = template.state == "closed"
    return {
        "head_branch": f"feature/{faker.word()}-{faker.pyint(100, 999)}",
        "base_branch": "main",
        "merged": merged,
        "merged_at": iso(updated_at) if merged else None,
        "reviewers": random.sample(TEAM_MEMBERS[:-1], k=2),
    }

def build_record(template: IssueTemplate, number: int, base_date: datetime) -> dict:
    created_at = base_date + timedelta(days=random.randint(0, 14), hours=random.randint(0, 18))
    updated_at = created_at + timedelta(hours=random.randint(2, 48))
    assignees = template.assignees or [choose_user(exclude={"triage-bot"})]
    assignees = list(dict.fromkeys(assignees))
    comments: List[dict] = []
    cursor = created_at
    for _ in range(template.comment_count):
        cursor += timedelta(hours=random.randint(1, 36))
        comments.append(make_comment(choose_user(), cursor))

    repo_meta = REPOSITORIES[template.repo]

    record = {
        "repository": {
            "id": template.repo,
            "name": repo_meta["description"],
            "description": repo_meta["description"],
            "languages": repo_meta["languages"],
            "topics": repo_meta["topics"],
            "default_branch": "main",
            "html_url": f"https://sandbox.example/{template.repo}",
        },
        "issue": {
            "id": f"{template.repo}-{number}",
            "number": number,
            "title": template.title,
            "body": template.body,
            "state": template.state,
            "author": choose_user(),
            "assignees": assignees,
            "created_at": iso(created_at),
            "updated_at": iso(updated_at),
            "is_pull_request": template.kind == "pull_request",
        },
        "pull_request": generate_pull_request(template, created_at, updated_at),
        "labels": [label_payload(label) for label in template.labels],
        "comments": comments,
        "events": generate_events(template, created_at, updated_at),
        "duplicate_group": template.duplicate_group,
    }
    return record


def generate_dataset(multiplier: int = DEFAULT_MULTIPLIER) -> List[dict]:
    """Produce GitHub-style issues by iterating through the template library."""

    if multiplier < 1:
        raise ValueError("multiplier must be greater than or equal to 1")

    repo_counters = defaultdict(lambda: 100)
    start_date = datetime(2024, 5, 17, tzinfo=timezone.utc)
    records: List[dict] = []

    for cycle in range(multiplier):
        base_date = start_date + timedelta(days=CYCLE_SPACING_DAYS * cycle)
        for template in ISSUE_LIBRARY:
            repo_counters[template.repo] += 1
            number = repo_counters[template.repo]
            records.append(build_record(template, number, base_date))
    return records


def write_jsonl(records: Iterable[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--multiplier",
        type=int,
        default=DEFAULT_MULTIPLIER,
        help=(
            "Numer of passes through the issue template library."
            "Total records equal len(ISSUE_LIBRARY) * multiplier."
        ),
    )
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    dataset = generate_dataset(multiplier=args.multiplier)
    write_jsonl(dataset, OUTPUT_PATH)
    print(
        "Wrote {count} GitHub issues records (multiplier={multiplier}) to {path}".format(
            count=len(dataset),
            multiplier=args.multiplier,
            path=OUTPUT_PATH.relative_to(ROOT),
        )
    )


if __name__ == "__main__":
    main()

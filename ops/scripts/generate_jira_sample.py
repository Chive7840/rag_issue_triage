"""Generate deterministic Jira-style issues for the sandbox dataset.

Use ``--multiplier`` to scale the resulting payload while keeping the same
set of canonical workflow examples.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from faker import Faker



ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT / "db" / "sandbox" / "jira_issues.jsonl"
DEFAULT_MULTIPLIER = 3
CYCLE_SPACING_DAYS = 14

faker = Faker()
RANDOM_SEED = 20240517
random.seed(RANDOM_SEED)
faker.seed_instance(RANDOM_SEED)


TEAM_MEMBERS = [
    "Aria Patel",
    "Mike Flores",
    "Chen Blake",
    "Luis Raman",
    "Samira Rivers",
    "Sasha Moroz",
]


PROJECTS = {
    "RAG": {
        "name": "RAG Issue Triage",
        "lead": "Aria Patel",
        "components": ["Ingestion", "Embeddings", "Triage"],
    },
    "OPS": {
        "name": "Platform Operations",
        "lead": "Mike Flores",
        "components": ["Deployments", "Runbooks", "Observability"],
    },
    "ANALYTICS": {
        "name": "Platform Analytics",
        "lead": "Luis Raman",
        "components": ["HealthCheck", "Dashboards", "Automation"]
    },
}


@dataclass(frozen=True)
class JiraIssueTemplate:
    project: str
    summary: str
    description: str
    issue_type: str
    priority: str
    workflow: List[str]
    labels: Optional[List[str]] = None
    comment_count: int = 1
    epic_link: Optional[str] = None


WORKFLOWS = {
    "default": ["To Do", "In Progress", "In Review", "Done"],
    "ops_incident": ["To Do", "In Progress", "Resolved"],
    "analysis": ["To Do", "In Progress", "Blocked", "In Progress", "Done"],
}


ISSUE_LIBRARY: List[JiraIssueTemplate] = [
    JiraIssueTemplate(
        project="RAG",
        summary="Design sandbox data seeding flow",
        description=(
            "Document how synthetic GitHub and Jira datasets are generated and loaded into the sandbox. "
            "Include commands for developers and add automated checks for schema drift."
        ),
        issue_type="Story",
        priority="High",
        workflow=WORKFLOWS["default"],
        labels=["sandbox", "docs"],
        comment_count=2,
        epic_link="RAG-EPIC-1",
    ),
    JiraIssueTemplate(
        project="RAG",
        summary="Investigate embedding mismatches in triage suggestions",
        description=(
            "Compare embeddings produced locally with those bundled in the sandbox. "
            "Identify any discrepancies and capture reproduction steps."
        ),
        issue_type="Bug",
        priority="Highest",
        workflow=WORKFLOWS["analysis"],
        labels=["embeddings", "quality"],
        comment_count=3,
    ),
    JiraIssueTemplate(
        project="OPS",
        summary="Runbook: reset sandbox database",
        description=(
            "Create a scripted procedure that drops and recreates sandbox tables, "
            "reloads seed data, and refreshes embeddings."
        ),
        issue_type="Task",
        priority="Medium",
        workflow=WORKFLOWS["default"],
        labels=["runbook"],
        comment_count=1,
    ),
    JiraIssueTemplate(
        project="OPS",
        summary="Incident: Redis saturation during demo",
        description=(
            "During the live walkthrough Redis hit 95% memory usage."
            "Investigate if background jobs are leaking keys and propose remediation steps."
        ),
        issue_type="Incident",
        priority="Highest",
        workflow=WORKFLOWS["ops_incident"],
        labels=["incident", "redis"],
        comment_count=2,
    ),
    JiraIssueTemplate(
        project="RAG",
        summary="Adopt reusable GitHub triage prompts",
        description=(
            "Curate a shared library of prompts used to generate synthetic GitHub issues "
            "so datasets stay consistent across releases."
        ),
        issue_type="Story",
        priority="Medium",
        workflow=WORKFLOWS["default"],
        labels=["prompt-library"],
        comment_count=1,
        epic_link="RAG-EPIC-1",
    ),
]


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def choose_user(exclude: Optional[Iterable[str]] = None) -> str:
    exclude_set = set(exclude or [])
    candidates = [person for person in TEAM_MEMBERS if person not in exclude_set]
    return random.choice(candidates)


def make_comment(created_at: datetime) -> dict:
    return {
        "author": choose_user(),
        "body": faker.paragraph(nb_sentences=2),
        "created_at": iso(created_at),
    }


def build_transitions(workflow: List[str], created_at: datetime) -> List[dict]:
    transitions: List[dict] = []
    cursor = created_at
    previous = workflow[0]
    for current in workflow[1:]:
        cursor += timedelta(hours=random.randint(4, 24))
        transitions.append(
            {
                "from": previous,
                "to": current,
                "actor": choose_user(),
                "timestamp": iso(cursor),
            }
        )
        previous = current
    return transitions


def build_record(template: JiraIssueTemplate, sequence: int, base_date: datetime) -> dict:
    created_at = base_date + timedelta(days=random.randint(0, 10), hours=random.randint(7, 18))
    transitions = build_transitions(template.workflow, created_at)
    updated_at = created_at if not transitions else datetime.fromisoformat(
        transitions[-1]["timestamp"].replace("Z", "+00:00")
    )
    comments: List[dict] = []
    cursor = created_at
    for _ in range(template.comment_count):
        cursor += timedelta(hours=random.randint(6, 30))
        comments.append(make_comment(cursor))

    project_meta = PROJECTS[template.project]
    issue_key = f"{template.project}-{sequence}"
    assignee = choose_user()

    record = {
        "project": {
            "key": template.project,
            "name": project_meta["name"],
            "lead": project_meta["lead"],
            "components": project_meta["components"],
        },
        "issue": {
            "key": issue_key,
            "summary": template.summary,
            "description": template.description,
            "type": template.issue_type,
            "priority": template.priority,
            "status": template.workflow[-1],
            "labels": template.labels or [],
            "reporter": choose_user(exclude={assignee}),
            "assignee": assignee,
            "epic_link": template.epic_link,
            "created_at": iso(created_at),
            "updated_at": iso(updated_at),
        },
        "transitions": transitions,
        "comments": comments,
    }
    return record


def generate_dataset(multiplier: int = DEFAULT_MULTIPLIER) -> List[dict]:
    """Produce Jira-style issues by iterating through the template library."""

    if multiplier < 1:
        raise ValueError("multiplier must be greater than or equal to 1")

    counters = {project: 100 for project in PROJECTS.keys()}
    start_date = datetime(2024, 3, 20, tzinfo=timezone.utc)
    records: List[dict] = []

    for cycle in range(multiplier):
        base_date = start_date + timedelta(days=CYCLE_SPACING_DAYS * cycle)
        for template in ISSUE_LIBRARY:
            counters[template.project] += 1
            records.append(
                build_record(template, counters[template.project], base_date)
            )
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
            "Number of passes through the Jira issue template library. "
            "Total records equal len(ISSUE_LIBRARY) * multiplier."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = generate_dataset(multiplier=args.multiplier)
    write_jsonl(dataset, OUTPUT_PATH)
    print(
        "Wrote {count} Jira issue records (multiplier={multiplier}) to {path}".format(
            count=len(dataset),
            multiplier=args.multiplier,
            path=OUTPUT_PATH.relative_to(ROOT),
        )
    )


if __name__ == "__main__":
    main()

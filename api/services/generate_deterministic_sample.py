"""
Deterministic synthetic GitHub/Jira issue generation.

- No external deps. Requires only stdlib.
- Emits .ndjson (optionally gzipped) or prints JSON lines to stdout.
- Tunable vis CLI args; stable via seed.

Usage example -- GitHub:
``python generate_deterministic_sample.py --flavor github -n 750 --seed demo-42 --days 30 -o ../../db/sandbox/github_issues.ndjson``

Usage example -- Jira:
``python generate_deterministic_sample.py --flavor jira   -n 750  --seed demo-42 --days 30 -o ../../db/sandbox/jira_issues.ndjson``

    Optional:
        Add `.gz` after `.ndjson` at the end of each command to compress the data.
"""

from __future__ import annotations
import argparse, gzip, json, math, sys, logging, os, random, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sympy.physics.secondquant import contraction

from api.services.paraphrase_engine import (
    BaseParaphraser,
    LockedEntityGuard,
    LLMParaphraser,
    ProviderRegistry,
)


# ----------- github repo name generator -----------
orgs = ["hirokawa", "tanaka", "aoyama", "nishinoen", "yoshida", "nagisa",
        "rizzi-coppola", "montanari", "sartori-group", "cattaneo", "bianchi"]
services = ["auth", "billing", "search", "orders", "metrics", "notifications",
            "ai-engineering", "data-solutions", "data-analysis", "app-building"]
suffixes = ["api", "service", "worker", "frontend", "backend", "cli", "full-stack",
            "databases"]
stacks = ["node", "react", "go", "python", "spark", "c++", "docker", "rust"]
fun = ["octo", "quantum", "rusty", "neon", "plasma"]
others = ["sushi", "penguin", "train", "llama", "grass", "ink"]

def gen_repo(rng: random.Random):
    """Generate a synthetic repository name using weighted templates."""

    pattern = rng.choice([1,2,3,4,5])
    if pattern == 1:
        return f"{rng.choice(orgs)}-{rng.choice(suffixes)}"
    if pattern == 2:  # service + suffix
        return f"{rng.choice(services)}-{rng.choice(suffixes)}"
    if pattern == 3:  # feature + stack
        return f"{rng.choice(services)}-{rng.choice(stacks)}"
    if pattern == 4:  # infra/exp
        return f"{rng.choice(['infra','exp'])}-{rng.choice(services)}"
    if pattern == 5:  # fun style
        return f"{rng.choice(fun)}-{rng.choice(others)}"


def gen_repos(n: int, seed: int = 42) -> list[str]:
    """Return ``n`` unique-ish repository slugs for sampling fixtures."""

    rng = random.Random(seed)
    repo_list = list({gen_repo(rng) for _ in range(n*2)})[:n] # oversample then dedupe
    return repo_list


# ----------- compact config -----------
repos = gen_repos(15)
CONFIG = {
    "repos": repos,
    "project_keys" : ["ITSM", "ACME", "Default", "DEV", "DevOps", "RAG", "Metrics",
                    "Dashboard", "Database", "DBSM", "React", "Redis", "node"],
    "components": ["auth", "payments", "search", "webhook", "cache", "etl", "ui"],
    "users": ["maria", "nushi", "mohammed", "jose", "wei", "yan", "john", "carlos",
              "aleksandr", "ping", "anita", "ram"],
    "labels": ["bug", "regression", "good first issue", "help wanted", "documentation",
               "performance", ""],
    "issue_types_github": ["Bug", "Triage", "Enhancement", "UX", "Task", "Analytics",
                           "Metrics", "Documentation", "High Priority", "Dependencies"],
    "issue_types_jira": ["Bug", "Story", "Task", "Epic", "Sub-Task", "UX", "Triage",
                         "Analytics", "Metrics", "Documentation", "Dependencies"],
    "hourly_weight": [2,1,1,1,1,1,2,4,6,8,9,8,7,7,7,8,9,8,6,5,4,3,3,2],
    "p_duplicate": 0.06,
    "p_burst": 0.35,
    "templates": [
        "{component}: {verb} {object} when {condition}",
        "[{scope}] {component} fails on {env} with {error_class} ({code})",
        "{component} {verb_past} after {action} in {env}",
        "Regression: {object} {verb} on {branch} since {version}"
    ],
    "lex": {
        "component": ["auth", "payments", "search", "webhook", "cache", "etl", "ui"],
        "verb": ["fails", "crashes", "misroutes", "deadlocks", "panics", "times out"],
        "verb_past": ["regressed", "crashed", "deadlocked", "hung", "timed out"],
        "object": ["OAuth flow", "pagination", "retry logic", "webhook", "cache eviction", "feature flag"],
        "condition": ["token expired", "cold start", "network jitter", "zero results", "large payload"],
        "scope": ["api", "ui", "docs", "infra", "metrics", "network", "optimization"],
        "env": ["Chrome 126", "Node 20", "Ubuntu 22.04", "iOS 17", "k8s GKE"],
        "error_class": ["NullPointerException", "TypeError", "KeyError", "TimeoutError", "UNAVAILABLE"],
        "code": ["ERR_AUTH_401", "EINVALID_STATE", "ECONNRESET", "504", "SIGSEGV"],
        "action": ["deploy", "rollback", "feature flag toggle", "scheme migration", "cache clear"],
        "branch": ["main", "release/2025.10", "hotfix/auth-401"],
        "version": ["v2.3.1", "v2.4.0-rc1", "2025.10.0"],
        "steps": [
            "Go to settings and enable feature flag",
            "Sign in with test account",
            "Call /v1/auth/refresh",
            "Open devtools network tab",
            "Observe 504 on POST /token"
        ],
        "reactions": [":thumbsup:", ":eyes:", ":rocket:", ":bug:"]
    },
    # minimal FSMs
    "fsm_github": {
        "Bug": {
            "Open": [("Triaged", 0.7), ("Closed", 0.1), ("Backlog", 0.2)],
            "Triaged": [("In Progress", 0.6), ("Backlog", 0.3), ("Closed", 0.1)],
            "In Progress": [("Review", 0.6), ("Closed", 0.3), ("Blocked", 0.1)],
            "Review": [("Closed", 0.75), ("Reopened", 0.1), ("In Progress", 0.15)],
            "Blocked": [("In Progress", 0.7), ("Backlog", 0.3)],
            "Backlog": [("Triaged", 0.5), ("Closed", 0.5)],
            "Reopened": [("In Progress", 0.8), ("Backlog", 0.2)],
            "Closed": []
        }
    },
    "fsm_jira": {
        "Bug": {
            "To do": [("In Progress", 0.7), ("Done", 0.05), ("Backlog", 0.25)],
            "In Progress": [("In Review", 0.6), ("Blocked", 0.2), ("Done", 0.2)],
            "In Review": [("Done", 0.75), ("Reopened", 0.15), ("In Progress", 0.1)],
            "Blocked": [("In Progress", 0.7), ("Backlog", 0.3)],
            "Backlog": [("To Do", 1.0)],
            "Reopened": [("In Progress", 0.9), ("Backlog", 0.1)],
            "Done": []
        }
    }
}

PARAPHRASE_FIELDS = {"context", "steps", "expected", "actual", "notes"}

def _word_count(text: str) -> int:
    """Count words in ``text`` using a lightweight regex."""

    return len(re.findall(r"\b\w+\b", text))


# ----------- utils -----------
def wchoice(rng: random.Random, pairs: List[Tuple[str, float]]) -> str:
    """Draw a value from ``pairs`` where the second item is the weight."""

    total = sum(w for _, w in pairs)
    r = rng.random() * total
    for v, w in pairs:
        r -= w
        if r <= 0:
            return v
    return pairs[-1][0]


def poisson_knuth(rng: random.Random, lam: float) -> int:
    """Sample a Poisson-distributed cou t via Knuth's algorithm."""

    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def lognormal(rng: random.Random, mu: float, sigma: float) -> float:
    """Return a log-normal sample using the random generator ``rng``."""

    return math.exp(rng.normalvariate(mu, sigma))


def sample_created_at(rng: random.Random, base: datetime, i: int, hourly_w: List[int], days: int) -> datetime:
    """Spread issues across ``days`` while weighting by hour-of-day."""

    # spread issues over past `days`, weight by hour-of-day
    day = i % days
    hour = wchoice(rng, [(h, w) for h, w in enumerate(hourly_w)])
    minute = rng.randrange(0, 60)
    return base + timedelta(days=day, hours=int(hour), minutes=minute)


def title_from_tpl(rng: random.Random, tpl: str, lex: Dict[str, List[str]]) -> str:
    """Fill ``tpl`` placeholders with random picks from ``lex``."""

    out = tpl
    for key, vals in lex.items():
        token = "{%s}" % key
        if token in out:
            out = out.replace(token, rng.choice(vals))
    return " ".join(out.split())


def body_md(rng: random.Random, lex: Dict[str, List[str]], env: str) -> str:
    """Assemble a mini-markdown body referencing environment ``env``."""

    s1, s2 = rng.choice(lex["steps"]), rng.choice(lex["steps"])
    expected = "200 OK" if rng.random() < 0.5 else "success toast"
    got = "504 Gateway Timeout" if rng.random() < 0.5 else "TypeError: undefined"
    return "\n".join([
        "### Environment",
        f"- {env}",
        "",
        "### Steps to Reproduce",
        f"- {expected}",
        "### Actual",
        f"- {got}",
    ])


def walk_fsm(rng: random.Random, flavor: str, issue_type: str, created: datetime) -> Tuple[List[dict], str, datetime]:
    """Simulate workflow transitions for an issue lifecycle."""

    fsm = CONFIG["fsm_github"] if flavor == "github" else CONFIG["fsm_jira"]
    graph = fsm.get(issue_type) or fsm.get("Bug", {})
    start = "Open" if flavor == "github" else "To Do"
    state, t = start, created
    transitions: List[dict] = []
    steps = 1 + min(6, poisson_knuth(rng, 2.0))
    for _ in range(steps):
        outs = graph.get(state, [])
        if not outs:
            break
        to = wchoice(rng, outs)
        dt_min = max(5, int(lognormal(rng, 5.7, 0.8))) # minutes
        t = t + timedelta(minutes=dt_min)
        transitions.append({"from": state, "to": to, "at": t.astimezone(timezone.utc).isoformat()})
        state = to
    last = transitions[-1]["to"] if transitions else start
    return transitions, last, t


def synth_comments(
        rng: random.Random,
        users: List[str],
        created: datetime,
        end_at: datetime,
        p_burst: float,
) -> List[dict] :
    """Create lightweight synthetic comments between ``created`` and ``end_at``."""

    base = poisson_knuth(rng, 0.6)
    extra = (1 + poisson_knuth(rng, 1.2)) if rng.random() < p_burst else 0
    total = min(12, base + extra)
    comments = []
    span = (end_at - created).total_seconds()
    for _ in range(total):
        at = created + timedelta(seconds=int(rng.random() * max(1, span)))
        body = "LGTM" if rng.random() < 0.3 else ("Can you add logs?" if rng.random() < 0.5 else "Repro confirmed.")
        comments.append({
            "id": f"c_{rng.choice(users)}_{rng.randrange(36**6):06x}",
            "author": rng.choice(users),
            "at": at.astimezone(timezone.utc).isoformat(),
            "body": body
        })
    comments.sort(key=lambda c: c["at"])
    return comments

def _apply_paraphrase(
        paraphraser: BaseParaphraser,
        guard: LockedEntityGuard,
        text: Optional[str],
) -> str:
    """Apply paraphrasing while preserving locked entities."""

    if text is None or not text.strip():
        return text or ""
    masked, replacements = guard.mask(text)
    constraints = None
    if replacements:
        constraints = {"do_not_change": [placeholder for placeholder, _ in replacements]}
    result = paraphraser.paraphrase(masked, constraints=constraints)
    return guard.unmask(result.text, replacements)


def synth_issue(
        rng: random.Random,
        i: int,
        flavor: str,
        days_span: int,
        paraphraser: BaseParaphraser,
        guard: LockedEntityGuard,
) -> dict:
    """Produce a deterministic-ish issue payload for ``flavor``."""

    repos = CONFIG["repos"]; projects = CONFIG["project_keys"]
    comps = CONFIG["components"]; users = CONFIG["users"]; labels_all = CONFIG["labels"]
    types = CONFIG["issue_types_github"] if flavor == "github" else CONFIG["issue_types_jira"]
    hourly = CONFIG["hourly_weight"]; lex = CONFIG["lex"]; tpls = CONFIG["templates"]

    repo = rng.choice(repos) if flavor == "github" else None
    project = rng.choice(projects) if flavor == "jira" else None
    component = rng.choice(comps)
    reporter = rng.choice(users)
    assignee = rng.choice([u for u in users if u != reporter]) if rng.random() < 0.9 else None
    labels = list({rng.choice(labels_all) for _ in range (1 + rng.randrange(0, 3))})
    priority = ["P0", "P1", "P2", "P3"][rng.randrange(0, 4)]
    issue_type = rng.choice(types)

    base = datetime.now(timezone.utc) -  timedelta(days=days_span + 5)
    created = sample_created_at(rng, base, i, hourly, days_span)
    tpl = rng.choice(tpls)
    env = rng.choice(lex["env"])
    title = _apply_paraphrase(paraphraser, guard, title_from_tpl(rng, tpl, lex))
    body = _apply_paraphrase(paraphraser, guard, body_md(rng, lex, env))
    version_tag = rng.choice(lex["version"])
    error_class = rng.choice(lex["error_class"])
    file_path = f"services/{component}/handler.py"
    status_url = f"https://status.example.com/{component}"
    inline_toggle = f"{component}_retry"
    steps_selected = rng.sample(lex["steps"], k=2)
    context_section = (
        f"{component} incident observed in {env} after deploying version {version_tag}."
    )
    steps_section = "\n".join(
        f"{idx + 1}. {step}" for idx, step in enumerate(steps_selected)
    )
    expected_section = (
        f"The {component} workflow should return 200 OK without extra retries."
    )
    actual_section = (
        f"{error_class} raised from {file_path} while calling {steps_selected[0].split()[0]}"
        f" and hitting {status_url}."
    )
    notes_section = (
        f"Review `{inline_toggle}` flag output and logs at /var/log/{component}.service. "
        f"See {status_url} for rollout notes in {repo or project or 'sandbox'} and keep"
        f" reference commit pinned."
    )

    transitions, last_state, end_at = walk_fsm(rng, flavor, issue_type, created)
    comments = synth_comments(rng, users, created, end_at, CONFIG["p_burst"])
    for comment in comments:
        comment["body"] = _apply_paraphrase(paraphraser, guard, comment.get("body", ""))
    closed_at = end_at.isoformat() if last_state in ("Closed", "Done") else None

    if rng.random() < CONFIG["p_duplicate"] and "duplicate" not in labels:
        labels.append("duplicate")

    out = {
        "id": f"{flavor}_{rng.randrange(36**10):010x}",
        "number": i + 1,
        "title": title,
        "body": body,
        "type": issue_type,
        "priority": priority,
        "labels": labels,
        "reporter": reporter,
        "assignee": assignee,
        "component": component,
        "repo": repo,
        "projectKey": project,
        "sprint": f"SPR-{1 + rng.randrange(0,20)}" if flavor == "jira" and rng.random() < 0.5 else None,
        "createdAt": created.isoformat(),
        "updatedAt": end_at.isoformat(),
        "closedAt": closed_at,
        "transitions": transitions,
        "comments": comments,
        "context": context_section,
        "steps": steps_section,
        "expected": expected_section,
        "actual": actual_section,
        "notes": notes_section,
    }
    return out

# ----------- cli -----------
def main():
    """Command-line entrypoint for deterministic dataset generation."""

    p = argparse.ArgumentParser(description="Synthesize GitHub/Jira issues")
    p.add_argument("--flavor", choices=["github", "jira"], required=True)
    p.add_argument("-n", "--num", "--count", dest="num", type=int, default=1500)
    p.add_argument("--seed", type=str, default="demo-42")
    p.add_argument("--days", type=int, default=30, help="spread creation over past N days")
    p.add_argument("-o", "--out", type=str, default="-", help="output path (.ndjson or .ndjson.gz")
    p.add_argument(
        "--paraphrase",
        choices=["off", "rule", "hf_local"],
        default="rule",
        help="Paraphrase provided to apply to titles, bodies, and comments.",
    )
    p.add_argument(
        "--paraphrase-budget",
        type=int,
        default=15,
        help="Maximum token edits allowed per section during paraphrasing.",
    )
    default_model = os.getenv("PARAPHRASE_MODEL", "ts-small")
    default_cache = os.getenv("HF_CACHE_DIR", ".cache/hf")
    default_allow = os.getenv("HF_ALLOW_DOWNLOADS", "").lower() in {"1", "true", "yes"}
    p.add_argument(
        "--paraphrase-max-edits-ratio",
        type=float,
        default=0.25,
        help="Maximum fraction of tokens that may change in a section.",
    )
    p.add_argument("--hf-model", type=str, default=None, help="Model name for hf_local provider")
    p.add_argument(
        "--hf-cache",
        type=str,
        default=None,
        help="Cache directory containing Hugging Face models for hf_local",
    )
    p.add_argument(
        "--hf-allow-downloads",
        action="store_true",
        help="Permit hf_local provider to download models if missing locally.",
    )
    args = p.parse_args()

    rng = random.Random(args.seed)
    write_gzip = args.out.endswith(".gz")
    sink = sys.stdout

    guard = LockedEntityGuard()
    paraphraser = ProviderRegistry.get(
        args.paraphrase,
        seed=args.seed,
        paraphrase_budget=args.paraphrase_budget,
        max_edits_ratio=args.paraphrase_max_edits_ratio,
        model_name=args.hf_model,
        cache_dir=args.hf_cache,
        allow_downloads=args.hf_allow_downloads,
    )

    if args.out != "-":
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        if write_gzip:
            sink = gzip.open(args.out, "wt", encoding="utf-8")
        else:
            sink = open(args.out, "w", encoding="utf-8")

    try:
        for i in range(args.num):
            rec = synth_issue(rng, i, args.flavor, args.days, paraphraser, guard)
            sink.write(json.dumps(rec, separators=(",",":")) + "\n")
    finally:
        if sink is not sys.stdout:
            sink.close()


if __name__ == "__main__":
    main()

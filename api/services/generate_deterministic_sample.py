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
from typing import Dict, List, Tuple



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

# ----------- utils -----------
def wchoice(rng: random.Random, pairs: List[Tuple[str, float]]) -> str:
    total = sum(w for _, w in pairs)
    r = rng.random()  * total
    for v, w in pairs:
        r -= w
        if r <= 0:
            return v
    return pairs[-1][0]


def poisson_knuth(rng: random.Random, lam: float) -> int:
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def lognormal(rng: random.Random, mu: float, sigma: float) -> float:
    return math.exp(rng.normalvariate(mu, sigma))


def sample_created_at(rng: random.Random, base: datetime, i: int, hourly_w: List[int], days: int) -> datetime:
    # spread issues over past `days`, weight by hour-of-day
    day = i % days
    hour = wchoice(rng, [(h, w) for h, w in enumerate(hourly_w)])
    minute = rng.randrange(0, 60)
    return base + timedelta(days=day, hours=int(hour), minutes=minute)


def title_from_tpl(rng: random.Random, tpl: str, lex: Dict[str, List[str]]) -> str:
    out = tpl
    for key, vals in lex.items():
        token = "{%s}" % key
        if token in out:
            out = out.replace(token, rng.choice(vals))
    return " ".join(out.split())


def body_md(rng: random.Random, lex: Dict[str, List[str]], env: str) -> str:
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


def synth_comments(rng: random.Random, users: List[str], created: datetime,end_at: datetime,
                   p_burst: float) -> List[dict]:
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


def synth_issue(rng: random.Random, i: int, flavor: str, days_span: int) -> dict:
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
    title = title_from_tpl(rng, tpl, lex)
    body = body_md(rng, lex, env)

    transitions, last_state, end_at = walk_fsm(rng, flavor, issue_type, created)
    comments = synth_comments(rng, users, created, end_at, CONFIG["p_burst"])
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
        "comments": comments
    }
    return out

# ----------- cli -----------
def main():
    p = argparse.ArgumentParser(description="Synthesize GitHub/Jira issues")
    p.add_argument("--flavor", choices=["github", "jira"], required=True)
    p.add_argument("-n", "--num", type=int, default=1500)
    p.add_argument("--seed", type=str, default="demo-42")
    p.add_argument("--days", type=int, default=30, help="spread creation over past N days")
    p.add_argument("-o", "--out", type=str, default="-", help="output path (.ndjson or .ndjson.gz")
    args = p.parse_args()

    rng = random.Random(args.seed)
    write_gzip = args.out.endswith(".gz")
    sink = sys.stdout

    if args.out != "-":
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        if write_gzip:
            sink = gzip.open(args.out, "wt", encoding="utf-8")
        else:
            sink = open(args.out, "w", encoding="utf-8")

    try:
        for i in range(args.num):
            rec = synth_issue(rng, i, args.flavor, args.days)
            sink.write(json.dumps(rec, separators=(",",":")) + "\n")
    finally:
        if sink is not sys.stdout:
            sink.close()


if __name__ == "__main__":
    main()

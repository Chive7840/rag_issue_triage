"""Integration coverage for the deterministic sample CLI."""

import json
import os
import re
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from api.services import generate_deterministic_sample as gds


def _run_cli(args):
    """Execute the CLI with ``args`` and return parsed JSON lines."""

    buffer = StringIO()
    argv_backup = sys.argv[:]
    sys.argv = [sys.argv[0], *args]
    try:
        with redirect_stdout(buffer):
            gds.main()
    finally:
        sys.argv = argv_backup
    output = buffer.getvalue().strip().splitlines()
    return [json.loads(line) for line in output if line.strip()]


def test_generator_without_paraphrase():
    """Baseline run without paraphrasing should produce canonical fields."""

    records = _run_cli(["--flavor", "github", "--num", "1", "--seed", "demo-42", "--days", "1", "--out", "-"])
    assert len(records) == 1
    issue = records[0]
    for field in ("context", "steps", "expected", "actual", "notes"):
        assert field in issue
    assert "status.example.com" in issue["notes"]
    assert "/var/log/" in issue["notes"]


def test_generator_rule_paraphrase_preserves_locks():
    """Rule paraphrasing must keep locked tokens intact."""

    base_records = _run_cli(["--flavor", "github", "--num", "1", "--seed", "demo-42", "--days", "1", "--out", "-"])
    baseline = base_records[0]
    records = _run_cli(
        [
            "--flavor",
            "github",
            "--num",
            "1",
            "--seed",
            "demo-42",
            "--days",
            "1",
            "--out",
            "-",
            "--paraphrase",
            "rule",
            "--paraphrase-budget",
            "6",
        ]
    )
    issue = records[0]
    base_path = re.search(r"/var/log/[^\s]+", baseline["notes"]).group(0)
    new_path = re.search(r"/var/log/[^\s]+", issue["notes"]).group(0)
    assert base_path == new_path
    assert "status.example.com" in issue["notes"]
    assert issue["context"]


@pytest.mark.skipif(os.getenv("HF_LOCAL_TEST") != "1", reason="hf_local integration disabled")
def test_generator_hf_local_optional(monkeypatch):
    """Optionally ensure hf_local paraphrasing behaves when cache is present."""

    cache_dir = Path(os.getenv("HF_CACHE_DIR", ".cache/hf"))
    if not cache_dir.exists():
        pytest.skip("no cached model available")
    records = _run_cli(
        [
            "--flavor",
            "github",
            "--num",
            "1",
            "--seed",
            "demo-42",
            "--days",
            "1",
            "--out",
            "-",
            "--paraphrase",
            "hf_local",
            "--hf-cache",
            str(cache_dir),
        ]
    )
    issue = records[0]
    assert "https://status.example.com" in issue["notes"]
    assert "/var/log/" in issue["notes"]
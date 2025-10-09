"""Tests for the deterministic issue generator paraphrasing hooks."""

import random

from api.services.generate_deterministic_sample import (
    _apply_paraphrase,
    synth_issue,
)
from api.services.paraphrase_engine import (
    BaseParaphraser,
    LockedEntityGuard,
    ParaphraseResult,
    ProviderRegistry,
)


class _MarkerParaphraser(BaseParaphraser):
    """Test double that appends a marker so we can detect calls."""

    def __init__(self) -> None:
        super().__init__(paraphrase_budget=999)

    def paraphrase(self, text: str, constraints=None):  # type: ignore[override]
        return ParaphraseResult(text=f"{text} ::dummy::", edited_tokens=0, total_tokens=len(text.split()))


def test_synth_issue_routes_sections_through_paraphraser():
    rng = random.Random("demo")
    guard = LockedEntityGuard()
    paraphraser = _MarkerParaphraser()

    issue = synth_issue(rng, 0, "github", 7, paraphraser, guard)

    assert issue["title"].endswith("::dummy::")
    assert issue["body"].endswith("::dummy::")
    assert issue["comments"], "Expected comments to be generated"
    assert all(comment["body"].endswith("::dummy::") for comment in issue["comments"])


def test_apply_paraphrase_preserves_locked_entities():
    guard = LockedEntityGuard()
    paraphraser = ProviderRegistry.get(
        "rule",
        seed="demo",
        paraphrase_budget=10,
        max_edits_ratio=0.5,
    )
    text = "Check `code` path /tmp/app and https://example.com for details"

    updated = _apply_paraphrase(paraphraser, guard, text)

    assert "`code`" in updated
    assert "/tmp/app" in updated
    assert "https://example.com" in updated
    assert updated.strip(), "Paraphrased text should not be empty"
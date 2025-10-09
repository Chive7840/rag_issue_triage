"""Unit coverage for the paraphrasing engine helpers."""

import pytest

from api.services.paraphrase_engine import (
    HFLocalParaphraser,
    LockedEntityGuard,
    RuleBasedParaphraser,
)


def _mask_and_paraphrase(text: str, paraphraser, guard: LockedEntityGuard, seed: str = "demo"):
    """Utility to run masking, paraphrasing, and unmasking in tests."""

    masked, spans = guard.mask(text)
    constraints = {"do_not_change": [original for _, original in spans]}
    if hasattr(paraphraser, "paraphrase"):
        if isinstance(paraphraser, HFLocalParaphraser):
            result = paraphraser.paraphrase(masked, constraints=constraints, seed=seed)
        else:
            result = paraphraser.paraphrase(masked, constraints=constraints)
    else:  # pragma: no cover - safety
        result = paraphraser(masked)
    unmasked = guard.unmask(result.text, spans)
    return result, unmasked


def test_rule_paraphraser_deterministic_and_preserves_locked_entities():
    """The rule provider should be deterministic and never alter locked spans."""

    text = (
        "It seems that repo/test fails on version v1.2.3.\n"
        "```python\nprint('hello')\n```\n"
        "TypeError occurs at 2024-05-01T12:34:56Z when hitting https://example.com/path."
    )
    guard = LockedEntityGuard()
    provider = RuleBasedParaphraser(seed="demo-seed", paraphrase_budget=5)
    result1, output1 = _mask_and_paraphrase(text, provider, guard)
    result2, output2 = _mask_and_paraphrase(text, provider, guard)

    assert result1.text == result2.text
    assert output1 == output2
    assert "repo/test" in output1
    assert "https://example.com/path" in output1
    assert "2024-05-01T12:34:56Z" in output1
    assert "```python\nprint('hello')\n```" in output1
    assert "It seems that" not in output1


def test_rule_paraphraser_budget_respected():
    """Ensure rule-based paraphrasing honours the configured budget."""

    text = "We noticed that the service fails repeatedly"
    guard = LockedEntityGuard()
    provider = RuleBasedParaphraser(seed="budget", paraphrase_budget=1)
    masked, spans = guard.mask(text)
    result = provider.paraphrase(masked)
    assert result.edited_tokens <= 1
    restored = guard.unmask(result.text, spans)
    assert "fails" in text and ("fails" in restored or "breaks" in restored)


def test_hf_local_requires_cached_model(monkeypatch, tmp_path):
    """hf_local must refuse to run when models are missing and downloads disabled."""

    transformers = pytest.importorskip("transformers")

    def fake_pipeline(*args, **kwargs):  # pragma: no cover - helper for clarity
        raise OSError("missing")

    monkeypatch.setattr(transformers, "pipeline", fake_pipeline)
    with pytest.raises(RuntimeError) as exc:
        HFLocalParaphraser(
            model_name="mock", cache_dir=tmp_path, allow_downloads=False, paraphrase_budget=2
        )
    assert "not available in cache" in str(exc.value)


def test_hf_local_paraphraser_preserves_locked_entities(monkeypatch, tmp_path):
    """hf_local should keep locked content intact while editing around it."""

    transformers = pytest.importorskip("transformers")

    class DummyPipe:
        def __call__(self, prompt, **kwargs):
            if isinstance(prompt, list):
                return [{"generated_text": prompt[0]}]
            text = prompt.replace("fails", "breaks")
            return [{"generated_text": text}]

    def fake_pipeline(*args, **kwargs):
        return DummyPipe()

    monkeypatch.setattr(transformers, "pipeline", fake_pipeline)
    provider = HFLocalParaphraser(
        model_name="t5-small",
        cache_dir=tmp_path,
        allow_downloads=False,
        paraphrase_budget=5,
    )
    guard = LockedEntityGuard()
    text = "repo/test fails at 2024-05-01 while hitting https://example.com/api."
    result, restored = _mask_and_paraphrase(text, provider, guard, seed="hf-demo")
    assert "repo/test" in restored
    assert "https://example.com/api" in restored
    assert "2024-05-01" in restored
    assert "breaks" in restored or "fails" in restored
    assert result.edited_tokens <= provider.paraphrase_budget
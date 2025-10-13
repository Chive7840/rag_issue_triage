"""Unit coverage for the paraphrasing engine helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import pytest
from numpy.f2py.auxfuncs import isintent_in

from api.services.paraphrase_engine import (
    HFApiParaphraser,
    LockedEntityGuard,
    ParaphraseResult,
    ProviderRegistry,
)


@dataclass
class DummyCall:
    prompt: str
    options: Dict[str, Any]


class DummyClient:
    """Minimal Hugging Face client stub used in tests."""

    def __init__(self, responses: List[Any]) -> None:
        self.responses = responses
        self.calls: List[DummyCall] = []


    def text_generation(self, prompt: str, **options: Any) -> Any:
        self.calls.append(DummyCall(prompt=prompt, options=options))
        if not self.responses:
            raise RuntimeError("No stubbed responses left")
        return self.responses.pop(0)

def _mask_and_paraphrase(
                         text: str,
                         client: DummyClient,
                         budget: int = 5,
) -> tuple[ParaphraseResult, str, DummyClient]:
    """Helper that runs the full mask -> paraphrase -> unmask cycle."""

    guard = LockedEntityGuard()
    masked, spans = guard.mask(text)
    constraints = {"do_not_change": [value for _, value in spans]}
    provider = HFApiParaphraser(paraphrase_budget=budget, client=client)
    result = provider.paraphrase(masked, constraints=constraints, seed="demo-seed")
    restored = guard.unmask(result.text, spans)
    return result, restored, client


def test_hf_api_paraphraser_preserves_locked_entities() -> None:
    """The Hugging Face API paraphraser must keep locked entities verbatim."""

    text = "Visit https://example.com/api for details on repo/test failing."
    replacement = "We revisited \uf8fd0\uf8fc while debugging repo/test."
    client = DummyClient(responses=[replacement])
    result, restored, stub = _mask_and_paraphrase(text, client)
    assert "https://example.com/api" in restored
    assert "repo/test" in restored
    assert result.edited_tokens <= result.total_tokens
    assert stub.calls[0].prompt.startswith("paraphrase: ")


def test_hf_api_paraphraser_respects_budget() -> None:
    """Large edits beyond the configured budget should be rejected."""

    text = "Service fails intermittently"
    client = DummyClient(responses=["This response is entirely rewritten with many different tokens."])
    result, restored, _ = _mask_and_paraphrase(text, client, budget=1)
    assert restored == text
    assert result.edited_tokens == 0


def test_provider_registry_supports_hf_api() -> None:
    """Registry should build an HFApiParaphraser with injected client."""

    client = DummyClient(responses=["No Change"])
    provider = ProviderRegistry.get("hf_api", client=client)
    assert isinstance(provider, HFApiParaphraser)
    result = provider.paraphrase("Plain text", constraints={})
    assert result.text


def test_provider_registry_off_switch() -> None:
    """Requesting the off provider should produce a no-op paraphraser."""

    provider = ProviderRegistry.get("off", paraphrase_budget=0)
    result = provider.paraphrase("Leave unchanged")
    assert isinstance(result, ParaphraseResult)
    assert result.text == "Leave unchanged"
    assert result.edited_tokens == 0


def test_unknown_provider_raises() -> None:
    """Ensure misconfigured providers surface a helpful error."""

    with pytest.raises(ValueError):
        ProviderRegistry.get("does-not-exist")

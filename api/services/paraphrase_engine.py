"""Utilities for protecting locked entities and paraphrasing issue text.

The paraphrasing stack delegates to Hugging Face's hosted ``t5-small``
inference API. :class:`LockedEntityGuard` masks sensitive entities before
paraphrasing and restores them afterward while
:class:`HFApiParaphraser` enforces token budgets and handles remote inference.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from api.utils.logging_utils import get_logger

ReplacementList = List[Tuple[str, str]]

logger = get_logger("api.services.paraphrase_engine")


@dataclass
class ParaphraseResult:
    """Summary of a paraphrasing attempt.

    Attributes
    __________
    text:
        The paraphrased (or original) output string.
    edited_tokens:
        Number of tokens that changed relative to the input.
    total_tokens:
        Total tokens in the source text. Used for reporting percentages.
    """

    text: str
    edited_tokens: int
    total_tokens: int


def _tokenize(text: str) -> List[str]:
    """Return a simple word-token list used for diff-style accounting."""

    return re.findall(r"\b\w+\b", text)


def _count_token_edits(source: Sequence[str], target: Sequence[str]) -> int:
    """Return an edit count similar to Levenshtein cost.

    The helper relies on :class:`difflib.SequenceMatcher` so we avoid pulling
    in extra dependencies. The logic treats replacements as the max of the
    removed and inserted token spans and accumulates insert/delete operations.
    """

    if not source and not target:
        return 0
    from difflib import SequenceMatcher

    matcher = SequenceMatcher(a=source, b=target)
    edits = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            edits += max(i2 - i1, j2 - j1)
        elif tag == "delete":
            edits += i2 - i1
        elif tag == "insert":
            edits += j2 - j1
    return edits


class LockedEntityGuard:
    """Mask and restore entities that must not be modified.

    The guard walks the text, captures spans such as URLs, stack traces, issue
    keys, inline/fenced code, and replaces them with high-Unicode placeholders.
    Paraphrasers work on the masked text and receive the placeholder/value
    mapping so the original entities can be restored verbatim afterwards.
    """

    _FENCE_PATTERN = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~", re.MULTILINE)
    _INLINE_CODE_PATTERN = re.compile(r"`[^`]+`")
    _URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
    _PATH_PATTERN = re.compile(r"(?:\.{1,2}/|/)[\w@~./-]+")
    _REPO_PATTERN = re.compile(r"\b[\w.-]+/[\w.-]+\b")
    _ISSUE_KEY_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
    _ID_PATTERN = re.compile(r"\b(?:id:?\s*#?\d{3,}|#\d{3,}|\d{5,})\b", re.IGNORECASE)
    _TIMESTAMP_PATTERN = re.compile(
        r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?)?\b"
    )
    _VERSION_PATTERN = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?\b")
    _ERROR_PATTERN = re.compile(r"\b[A-Z][A-Za-z0-9]+Error\b")
    _STACK_TRACE_PATTERN = re.compile(
        r"Traceback \(most recent call last\):[\s\S]+?(?=\n{2,}|\Z)", re.MULTILINE
    )


    def __init__(self) -> None:
        """Compile all patterns that we treat as immutable."""

        self._patterns: List[re.Pattern[str]] = [
            self._FENCE_PATTERN,
            self._STACK_TRACE_PATTERN,
            self._INLINE_CODE_PATTERN,
            self._URL_PATTERN,
            self._PATH_PATTERN,
            self._REPO_PATTERN,
            self._ISSUE_KEY_PATTERN,
            self._ID_PATTERN,
            self._TIMESTAMP_PATTERN,
            self._VERSION_PATTERN,
            self._ERROR_PATTERN,
        ]

    @staticmethod
    def _placeholder(idx: int) -> str:
        """Return a rarely used placeholder string for a captured span."""

        return f"\uf8ff{idx}\uf8fe"

    def mask(self, text: str) -> Tuple[str, List[Tuple[str, str]]]:
        """Mask all locked entities in ``text`` and return replacements.

        Returns
        -------
        Tuple[str, ReplacementList]
            A tuple of the masked text and a list of ``(placeholder, value)``
            pairs which can later be passed to :meth:`unmask`.
        """

        spans: List[Tuple[int, int, str]] = []
        for pattern in self._patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                if start == end:
                    continue
                overlap = False
                for existing_start, existing_end, _ in spans:
                    if not (end <= existing_start or start >= existing_end):
                        overlap = True
                        break
                if overlap:
                    continue
                spans.append((start, end, match.group(0)))
        if not spans:
            return text, []
        spans.sort(key=lambda item: item[0])
        result_parts: List[str] = []
        cursor = 0
        replacements: List[Tuple[str, str]] = []
        for idx, (start, end, value) in enumerate(spans):
            result_parts.append(text[cursor:start])
            placeholder = self._placeholder(idx)
            result_parts.append(placeholder)
            replacements.append((placeholder, value))
            cursor = end
        result_parts.append(text[cursor:])
        return "".join(result_parts), replacements

    def unmask(self, text: str, spans: Iterable[Tuple[str, str]]) -> str:
        """Restore the captured spans into ``text`` using ``spans`` mapping."""

        output = text
        for placeholder, value in spans:
            output = output.replace(placeholder, value)
        return output


class BaseParaphraser:
    """Base class offering shared budgeting logic for paraphrasers."""

    def __init__(self, paraphrase_budget: int, max_edits_ratio: float = 0.25) -> None:
        """Store budgeting parameters shared across concrete implementations."""

        self.paraphrase_budget = max(0, paraphrase_budget)
        self.max_edits_ratio = max(0.0, max_edits_ratio)

    def _allowed_edits(self, token_count: int) -> int:
        """Compute the maximum token edits permitted for ``token_count``."""

        if token_count == 0:
            return 0
        ratio_limit = int(token_count * self.max_edits_ratio)
        if self.max_edits_ratio > 0 and ratio_limit == 0:
            ratio_limit = 1
        limit = self.paraphrase_budget if self.paraphrase_budget > 0 else 0
        if limit == 0:
            return 0
        if ratio_limit == 0:
            return 0
        return min(limit, ratio_limit)

    def paraphrase(self, text: str, constraints: Optional[dict] = None) -> ParaphraseResult:
        """Return the original ``text`` while reporting token totals.

        This default implementation acts as a no-op paraphraser and is used
        when paraphrasing is disabled. Concrete subclasses should override the
        method while respecting the budgeting helpers.
        """

        return ParaphraseResult(text=text, edited_tokens=0, total_tokens=len(_tokenize(text)))


class LLMParaphraser(BaseParaphraser, ABC):
    """Shared scaffolding for paraphrasers backed by language models."""

    def __init__(self, paraphrase_budget: int, max_edits_ratio: float = 0.25) -> None:
        super().__init__(paraphrase_budget=paraphrase_budget, max_edits_ratio=max_edits_ratio)

    @abstractmethod
    def generate(self, text: str, constraints: Optional[Dict[str, Any]], seed: str) -> str:
        """Produce a paraphrased candidate for ``text``."""

    def paraphrase(self, text: str, constraints: Optional[Dict[str, Any]] = None, seed: str = "") -> ParaphraseResult:
        """Delegate to :meth:`generate` while enforcing the edit budget."""

        tokens = _tokenize(text)
        total_tokens = len(tokens)
        if not text.strip():
            return ParaphraseResult(text=text, edited_tokens=0, total_tokens=total_tokens)
        generated = self.generate(text=text, constraints=constraints or {}, seed=seed)
        target_tokens = _tokenize(generated)
        edits = _count_token_edits(tokens, target_tokens)
        allowed = self._allowed_edits(total_tokens)
        if edits > allowed:
            return ParaphraseResult(text=text, edited_tokens=0, total_tokens=total_tokens)
        return ParaphraseResult(text=generated, edited_tokens=edits, total_tokens=total_tokens)


class HFApiParaphraser(LLMParaphraser):
    """Paraphraser backed by Hugging Face's hosted inference API."""

    def __init__(
            self,
            model_name: Optional[str] = None,
            token: Optional[str] = None,
            paraphrase_budget: int = 15,
            max_edits_ratio: float = 0.25,
            max_new_tokens: int = 48,
            seed: str = "",
            client: Optional[Any] = None,
    ) -> None:

        super().__init__(paraphrase_budget=paraphrase_budget, max_edits_ratio=max_edits_ratio)
        self.model_name = model_name or os.getenv("PARAPHRASE_MODEL", "t5-small")
        self.max_new_tokens = max(1, max_new_tokens)
        self.seed = seed

        if client is not None:
            self._client= client
        else:
            try:
                from huggingface_hub import InferenceClient
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise RuntimeError("huggingface-hub is required for hf_api paraphrasing") from exc
            auth_token = token or os.getenv("HUGGING_FACE_API_TOKEN") or None
            self._client = InferenceClient(model=self.model_name, token=auth_token)
        self._needs_prefix = True


    def _apply_constraints(self, text: str, constraints: dict) -> Tuple[str, ReplacementList]:
        """Mask spans listed in ``constraints`` before generating."""

        protected = constraints.get("do_not_change") if constraints else None
        if not protected:
            return text, []
        replacements: ReplacementList = []
        updated = text
        for idx, item in enumerate(protected):
            placeholder = f"\uf8fd{idx}\uf8fc"
            replacements.append((placeholder, item))
            updated = updated.replace(item, placeholder)
        return updated, replacements

    def _restore_constraints(self, text: str, spans: Iterable[Tuple[str, str]]) -> str:
        """Restore masked spans in ``text`` using ``spans``."""

        restored = text
        for placeholder, value in spans:
            restored = restored.replace(placeholder, value)
        return restored

    def generate(self, text: str, constraints: Optional[Dict[str, Any]], seed: str) -> str:
        """Request a paraphrase from the Hugging Face inference API."""

        safe_text, spans = self._apply_constraints(text, constraints or {})
        prefix = "paraphrase: " if self._needs_prefix else ""
        prompt = prefix + safe_text
        options = {
            "max_new_tokens": self.max_new_tokens,
            "temperature": 0.0,
            "top_p": 1.0,
            "do_sample": False,
            "return_full_text": False,
        }
        try:
            response = self._client.text_generation(prompt, **options)
        except TypeError:
            options.pop("return_full_text", None)
            response = self._client.text_generation(prompt, **options)
        except Exception:
            logger.exception("Hugging Face paraphrase request failed")
            return text
        generated: Optional[str]
        if isinstance(response, str):
            generated = response
        elif isinstance(response, dict):
            generated = response.get("generated_text") or response.get("text")
        elif isinstance(response, (list, tuple)) and response:
            first = response[0]
            if isinstance(first, dict):
                generated = first.get("generated_text") or first.get("text")
            else:
                generated = getattr(first, "generated_text", None) or getattr(first, "text", None)
        else:
            generated = getattr(response, "generated_text", None) or getattr(response, "text", None)
        if not generated:
            generated = text
        else:
            generated = generated.strip() or text
        return self._restore_constraints(generated, spans)

class ProviderRegistry:
    """Factory helpers that produce configured paraphraser instances."""

    @staticmethod
    def get(name: str, **kwargs) -> BaseParaphraser:
        """Return a paraphraser by provider ``name``.

        Parameters
        ----------
        name:
            Provider key (``"off"`` | ``"hf_api"``).
        **kwargs:
            Extra keyword arguments forwarded to concrete paraphrasers.
        """

        normalized = (name or "hf_api").lower()
        if normalized in {"hf_api", "hf"}:
            return HFApiParaphraser(
                model_name=kwargs.get("model_name"),
                token=kwargs.get("token"),
                paraphrase_budget=kwargs.get("paraphrase_budget", 15),
                max_edits_ratio=kwargs.get("max_edits_ratio", 0.25),
                max_new_tokens=kwargs.get("max_new_tokens", 48),
                seed=kwargs.get("seed", ""),
                client=kwargs.get("client"),
            )
        if normalized in {"off", "none"}:
            return BaseParaphraser(paraphrase_budget=0)
        raise ValueError(f"Unknown paraphrase provider `{name}`")

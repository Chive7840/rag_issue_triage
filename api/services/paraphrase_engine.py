"""Utilities for protecting locked entities and paraphrasing issue text.

This module powers to paraphrasing strategies:

* :class:`RuleBasedParaphraser` applies deterministic edits (synonym swaps,
sentence shuffles, filler removal) under a strict budget.
* :class:`HFLocalParaphraser` wraps a local Hugging Face pipeline that can run
fully offline once a model is cached on disk.

Both strategies cooperate with :class:`LockedEntityGuard`, which masks sensitive
artifacts (URLS, stack traces, inline code, etc.) before paraphrasing and
restores them afterwards so downstream consumers see untouched protected spans.
"""

from __future__ import annotations

import json
import os
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

ReplacementList = List[Tuple[str, str]]

_CONFIG_CACHE: Optional[dict] = None


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


def _load_config() -> dict:
    """Load paraphraser configuration from :mod:`skeleton_config.yaml`.

    The configuration file is formatted as JSON to avoid a dependency on a YAML
    parser. We memoise the parsed structure to dodge repeated disk I/O because
    the paraphrasers are instantiated frequently during sampling.
    """

    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    config_path = Path(__file__).with_name("skeleton_config.yaml")
    if not config_path.exists():
        _CONFIG_CACHE = {}
        return _CONFIG_CACHE
    with config_path.open("r", encoding="utf-8") as handle:
        _CONFIG_CACHE = json.load(handle)
    return _CONFIG_CACHE


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
        replacements: List[Tuple[str, str]] =[]
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


class RuleBasedParaphraser(BaseParaphraser):
    """Deterministic paraphraser that performs template-driven edits."""

    _WORD_PATTERN = re.compile(r"\b\w+\b")

    def __init__(self, seed: str, paraphrase_budget: int, max_edits_ratio: float = 0.25) -> None:
        """Initialize the deterministic paraphraser using the shared config."""

        super().__init__(paraphrase_budget=paraphrase_budget, max_edits_ratio=max_edits_ratio)
        self.seed = seed
        cfg = _load_config()
        synonyms_cfg = cfg.get("synonyms", {})
        self.synonyms: Dict[str, List[str]] = {}
        for category in synonyms_cfg.values():
            for head, options in category.items():
                group = [head, *options]
                lowered = [word.lower() for word in group]
                for idx, word in enumerate(lowered):
                    replacements = [w for i, w in enumerate(lowered) if i != idx]
                    self.synonyms[word] = replacements
        self.filler_phrases = cfg.get("filler_phrases", [])
        self.voice_patterns = cfg.get("voice_patterns", {})

    @staticmethod
    def _match_case(source: str, template: str) -> str:
        """Mirror the capitalization style of ``template`` in ``source``."""

        if template.isupper():
            return source.upper()
        if template[0].isupper():
            return source.capitalize()
        return source

    def _remove_fillers(self, text: str, allowed: int, edits: int) -> Tuple[str, int]:
        """Remove filler phrases while respecting edit budgets."""

        for phrase in self.filler_phrases:
            if edits >= allowed:
                break
            words_removed = len([t for t in phrase.split() if t])
            if words_removed == 0:
                continue
            pattern = re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE)
            while edits < allowed:
                match = pattern.search(text)
                if not match:
                    break
                if edits + words_removed > allowed:
                    break
                start, end = match.span()
                text = text[:start] + text[end:]
                edits += words_removed
        return text, edits

    def _apply_synonyms(self, text: str, rng: random.Random, allowed: int, edits: int) -> Tuple[str, int]:
        """Swap eligible words with synonyms using deterministic randomness."""

        def repl(match: re.Match[str]) -> str:
            nonlocal edits
            if edits >= allowed:
                return match.group(0)
            word = match.group(0)
            if "\uf8ff" in word:
                return word
            lower = word.lower()
            if lower not in self.synonyms:
                return word
            options = [opt for opt in self.synonyms[lower] if opt != lower]
            if not options:
                return word
            replacement = rng.choice(options)
            replacement = self._match_case(replacement, word)
            if replacement == word:
                return word
            edits += 1
            return replacement

        return self._WORD_PATTERN.sub(repl, text), edits

    def _apply_voice_patterns(self, text: str, allowed: int, edits: int) -> Tuple[str, int]:
        """Toggle between passive/active voice per configured regex rules."""

        def apply(patterns: Iterable[dict], current: str, edits_in: int) -> Tuple[str, int]:
            edits_local = edits_in
            for entry in patterns:
                if edits_local >= allowed:
                    break
                regex = re.compile(entry.get("pattern", ""), re.IGNORECASE)
                template = entry.get("replacement", "")
                def _repl(match: re.Match[str]) -> str:
                    nonlocal edits_local
                    if edits_local >= allowed:
                        return match.group(0)
                    original = match.group(0)
                    if "\uf8ff" in original:
                        return original
                    data = {key: value for key, value in match.groupdict().items() if value is not None}
                    replacement = template.format(**data)
                    source_tokens = len(_tokenize(original))
                    target_tokens = len(_tokenize(replacement))
                    cost = max(source_tokens, target_tokens)
                    if cost == 0:
                        cost = 1
                    if edits_local + cost > allowed:
                        return original
                    edits_local += cost
                    return replacement
                current = regex.sub(_repl, current, count=1)
            return current, edits_local

        passive_patterns = self.voice_patterns.get("passive_to_active", [])
        active_patterns = self.voice_patterns.get("active_to_passive", [])
        text, edits = apply(passive_patterns, text, edits)
        text, edits = apply(active_patterns, text, edits)
        return text, edits

    def _reorder_sentences(self, text: str, rng: random.Random, allowed: int, edits: int) -> Tuple[str, int]:
        """Swap neighboring sentences to introduce light variation."""

        if edits >= allowed:
            return text, edits
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) < 2:
            return text, edits
        idx = rng.randrange(0, len(sentences) - 1)
        sentences[idx], sentences[idx + 1] = sentences[idx + 1], sentences[idx]
        cost = min(2, allowed - edits)
        edits += cost
        return " ".join(sentences), edits

    def paraphrase(self, text: str, constraints: Optional[dict] = None) -> ParaphraseResult:
        """Apply rule-based edits within the configured budget."""

        tokens = _tokenize(text)
        total_tokens = len(tokens)
        allowed = self._allowed_edits(total_tokens)
        if allowed == 0 or not text.strip():
            return ParaphraseResult(text=text, edited_tokens=0, total_tokens=total_tokens)
        rng = random.Random(f"{self.seed}:{text}")
        edits = 0
        updated = text
        updated, edits = self._remove_fillers(updated, allowed, edits)
        updated, edits = self._apply_synonyms(updated, rng, allowed, edits)
        updated, edits = self._apply_voice_patterns(updated, allowed, edits)
        if edits < allowed:
            updated, edits = self._reorder_sentences(updated, rng, allowed, edits)
        updated_tokens = _tokenize(updated)
        edits_count = _count_token_edits(tokens, updated_tokens)
        edits_count = min(edits_count, allowed)
        return ParaphraseResult(text=updated, edited_tokens=edits_count, total_tokens=total_tokens)


class LLMParaphraser(BaseParaphraser, ABC):
    """Shared scaffolding for paraphrasers backed by language models."""

    def __init__(self, paraphrase_budget: int, max_edits_ratio: float = 0.25) -> None:
        super().__init__(paraphrase_budget=paraphrase_budget, max_edits_ratio=max_edits_ratio)

    @abstractmethod
    def generate(self, text: str, constraints: Optional[str], seed: str) -> str:
        """Produce a paraphrased candidate for ``text``."""

    def paraphrase(self, text: str, constraints: Optional[dict] = None, seed: str = "") -> ParaphraseResult:
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


class HFLocalParaphraser(LLMParaphraser):
    """Local Hugging Face paraphraser constrained to cached models."""

    def __init__(
            self,
            model_name: Optional[str] = None,
            cache_dir: Optional[str] = None,
            allow_downloads: bool = False,
            paraphrase_budget: int = 15,
            max_edits_ratio: float = 0.25,
            seed: str = "",
    ) -> None:
        """Initialize the pipeline while respecting offline requirements."""

        super().__init__(paraphrase_budget=paraphrase_budget, max_edits_ratio=max_edits_ratio)
        self.model_name = model_name or os.getenv("PARAPHRASE_MODEL", "ts-small")
        cache_env = os.getenv("HF_CACHE_DIR", str(cache_dir) if cache_dir else ".cache/hf")
        self.cache_dir = Path(cache_dir or cache_env)
        if not cache_dir and not os.getenv("HF_CACHE_DIR"):
            self.cache_dir = Path(cache_env)
        allow_env = os.getenv("HF_ALLOW_DOWNLOADS")
        if allow_env is not None and not allow_downloads:
            allow_downloads = allow_env.lower() in {"1", "true", "yes"}
        self.allow_downloads = allow_downloads
        self.seed = seed
        self.max_new_tokens = 48
        try:
            from transformers import pipeline   # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("transformers is required for hf_local paraphrasing") from exc

        pipe_kwargs = {
            "model": self.model_name,
            "tokenizer": self.model_name,
            "cache_dir": str(self.cache_dir),
            "local_files_only": not self.allow_downloads,
            "task": "text2text-generation",
        }
        try:
            self._pipeline = pipeline(device_map="auto", **pipe_kwargs) # type: ignore[arg-type]
        except TypeError:
            pipe_kwargs.pop("task", None)
            self._pipeline = pipeline("text2text-generation", device_map="auto", **pipe_kwargs)
        except OSError as err:
            if not self.allow_downloads:
                raise RuntimeError(
                    f"Paraphrase model '{self.model_name}' not available in cache {self.cache_dir}."
                    "Allow downloads with --hf-allow-downloads to fetch it once."
                ) from err
            raise
        except Exception as err:    # pragma: no cover - fallback
            raise RuntimeError(f"Failed to initialize paraphrase model: {err}") from err
        try:
            self._pipeline(["test"], max_new_tokens=1)
        except Exception:
            pass
        lower_name = self.model_name.lower()
        self._needs_prefix = "ts" in lower_name or "flan" in lower_name

    def _apply_constraints(self, text: str, constraints: dict) -> Tuple[str, ReplacementList]:
        """Mask the ``do_not_change`` spans before running generation."""

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
        """Reinsert masked spans after language model generation."""

        restored = text
        for placeholder, value in spans:
            restored = restored.replace(placeholder, value)
        return restored

    def generate(self, text: str, constraints: Optional[dict], seed: str) -> str:
        """Generate a paraphrase through the local pipeline and unmask spans."""

        safe_text, spans = self._apply_constraints(text, constraints or{})
        prefix = "paraphrase: " if self._needs_prefix else ""
        prompt = prefix + safe_text
        options = {
            "max_new_tokens": self.max_new_tokens,
            "num_beams": 1,
            "do_sample": False,
            "temperature": 0.0,
        }
        outputs = self._pipeline(prompt, **options)
        if not outputs:
            return text
        candidate = outputs[0]
        generated = candidate.get("generated_text") or candidate.get("summary_text") or text
        generated = self._restore_constraints(generated, spans)
        return generated


class ProviderRegistry:
    """Factory helpers that produce configured paraphraser instances."""

    @staticmethod
    def get(name: str, **kwargs) -> BaseParaphraser:
        """Return a paraphraser by provider ``name``.

        Parameters
        ----------
        name:
            Provider key (``"off"`` | ``"rule"`` | ``"hf_local"``).
        **kwargs:
            Extra keyword arguments forwarded to concrete paraphrasers.
        """

        if name == "rule":
            seed = kwargs.get("seed", "")
            paraphrase_budget = kwargs.get("paraphrase_budget", 15)
            max_edits_ratio = kwargs.get("max_edits_ratio", 0.25)
            return RuleBasedParaphraser(seed=seed, paraphrase_budget=paraphrase_budget, max_edits_ratio=max_edits_ratio)
        if name == "hf_local":
            return HFLocalParaphraser(
                model_name=kwargs.get("model_name"),
                cache_dir=kwargs.get("cache_dir"),
                allow_downloads=kwargs.get("allow_downloads", False),
                paraphrase_budget=kwargs.get("paraphrase_budget", 15),
                max_edits_ratio=kwargs.get("max_edits_ratio", 0.25),
                seed=kwargs.get("seed", ""),
            )
        if name == "off":
            return BaseParaphraser(paraphrase_budget=0)
        raise ValueError(f"Unknown paraphrase provider `{name}`")

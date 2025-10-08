from __future__ import annotations

import json
import os
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

_CONFIG_CACHE: Optional[dict] = None


@dataclass
class ParaphraseResult:
    text: str
    edited_tokens: int
    total_tokens: int


def _tokenize(text: str) -> List[str]:
    return re.findall(r"\b\w+\b", text)


def _count_token_edits(source: Sequence[str], target: Sequence[str]) -> int:
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
    _FENCE_PATTERN = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~", re.MULTILINE)
    _INLINE_CODE_PATTERN = re.compile(r"`[^`]+`")
    _URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
    _PATH_PATTERN = re.compile(r"(?:\.{1,2}/|/)[\w@~./-]+")
    _REPO_PATTERN = re.compile(r"\b[\w.-]+/[\w.-]+\b")
    _ISSUE_KEY_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
    _ID_PATTERN = re.compile(r"\b(?:id:?\s*#?\d{3,}|#\d{3,}|\d{5,})\b", re.IGNORECASE)
    _TIMESTAMP_PATTERN = re.compile(
        r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}:\d{2}(?:z|[+-]\d{2}:\d{2})?)?\b"
    )
    _VERSION_PATTERN = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?\b")
    _ERROR_PATTERN = re.compile(r"\b[A-Z][A-za-z0-9]+Error\b")
    _STACK_TRACE_PATTERN = re.compile(
        r"Traceback \(most recent call last\):[\s\S]+?(?=\n{2,}|\z)", re.MULTILINE
    )



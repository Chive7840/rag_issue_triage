"""Sandbox bootstrap utilities for deterministic demo data."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:   # pragma: no cover - import for type checking only
    from .bootstrap import DEFAULT_DATA_DIR, ensure_embeddings, ensure_sample_data, run_cli

__all__ = [
    "DEFAULT_DATA_DIR",
    "ensure_embeddings",
    "ensure_sample_data",
    "run_cli",
]


def __getattr__(name: str) -> Any:  # pragma: no cover - thin import wrapper
    if name in __all__:
        from . import bootstrap

        return getattr(bootstrap, name)
    raise AttributeError(f"module 'api.sandbox' has no attribute {name!r}")

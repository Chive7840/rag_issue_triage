"""Sandbox bootstrap utilities for deterministic demo data."""

from .bootstrap import DEFAULT_DATA_DIR, ensure_embeddings, ensure_sample_data, run_cli

__all__ = [
    "DEFAULT_DATA_DIR",
    "ensure_embeddings",
    "ensure_sample_data",
    "run_cli",
]
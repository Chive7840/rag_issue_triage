"""Interface for cross-encoder reranking."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from ..schemas import RetrievalResult

class Reranker(ABC):
    @abstractmethod
    async def rerank(self, query: str, candidates: Sequence[RetrievalResult]) -> Sequence[RetrievalResult]:
        """Return reranked candidates for a query."""

class NoOpReranker(Reranker):
    async def rerank(self, query: str, candidates: Sequence[RetrievalResult]) -> Sequence[RetrievalResult]:
        return candidates
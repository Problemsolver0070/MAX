"""Embedding providers for Max's semantic search."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import voyageai

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts, returning a list of embedding vectors."""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """Return the dimensionality of the embedding vectors."""
        ...


class VoyageEmbeddingProvider(EmbeddingProvider):
    """Voyage AI embedding provider — Anthropic's recommended embedding partner."""

    def __init__(
        self,
        api_key: str,
        model: str = "voyage-3",
        dimension: int = 1024,
    ) -> None:
        self._client = voyageai.AsyncClient(api_key=api_key)
        self._model = model
        self._dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = await self._client.embed(texts, model=self._model)
        return result.embeddings

    def dimension(self) -> int:
        return self._dimension

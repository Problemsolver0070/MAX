"""Tests for embedding provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.memory.embeddings import EmbeddingProvider, VoyageEmbeddingProvider


class TestEmbeddingProviderABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            EmbeddingProvider()


class TestVoyageEmbeddingProvider:
    def test_dimension(self):
        with patch("max.memory.embeddings.voyageai"):
            provider = VoyageEmbeddingProvider(api_key="test-key")
            assert provider.dimension() == 1024

    def test_dimension_custom_model(self):
        with patch("max.memory.embeddings.voyageai"):
            provider = VoyageEmbeddingProvider(
                api_key="test-key", model="voyage-3-large", dimension=1024
            )
            assert provider.dimension() == 1024

    async def test_embed_single_text(self):
        with patch("max.memory.embeddings.voyageai") as mock_voyage:
            mock_client = AsyncMock()
            mock_voyage.AsyncClient.return_value = mock_client
            mock_result = MagicMock()
            mock_result.embeddings = [[0.1] * 1024]
            mock_client.embed.return_value = mock_result

            provider = VoyageEmbeddingProvider(api_key="test-key")
            embeddings = await provider.embed(["hello world"])

            assert len(embeddings) == 1
            assert len(embeddings[0]) == 1024
            mock_client.embed.assert_called_once_with(["hello world"], model="voyage-3")

    async def test_embed_multiple_texts(self):
        with patch("max.memory.embeddings.voyageai") as mock_voyage:
            mock_client = AsyncMock()
            mock_voyage.AsyncClient.return_value = mock_client
            mock_result = MagicMock()
            mock_result.embeddings = [[0.1] * 1024, [0.2] * 1024, [0.3] * 1024]
            mock_client.embed.return_value = mock_result

            provider = VoyageEmbeddingProvider(api_key="test-key")
            embeddings = await provider.embed(["a", "b", "c"])

            assert len(embeddings) == 3

    async def test_embed_empty_list(self):
        with patch("max.memory.embeddings.voyageai"):
            provider = VoyageEmbeddingProvider(api_key="test-key")
            embeddings = await provider.embed([])
            assert embeddings == []

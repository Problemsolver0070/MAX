"""Hybrid retrieval — graph + semantic + keyword search with RRF fusion."""

from __future__ import annotations

import logging
import uuid as uuid_mod

from max.db.postgres import Database
from max.memory.embeddings import EmbeddingProvider
from max.memory.graph import MemoryGraph
from max.memory.models import (
    HybridRetrievalQuery,
    RetrievalResult,
)

logger = logging.getLogger(__name__)


class RRFMerger:
    """Reciprocal Rank Fusion — merges ranked lists from multiple strategies."""

    @staticmethod
    def merge(
        strategy_results: dict[str, list[RetrievalResult]],
        weights: dict[str, float],
        k: int = 60,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        if not strategy_results:
            return []

        scores: dict[uuid_mod.UUID, float] = {}
        items: dict[uuid_mod.UUID, RetrievalResult] = {}
        strategies_map: dict[uuid_mod.UUID, list[str]] = {}

        for strategy_name, results in strategy_results.items():
            weight = weights.get(strategy_name, 1.0)
            for rank, result in enumerate(results):
                cid = result.content_id
                rrf_contribution = weight / (k + rank + 1)
                scores[cid] = scores.get(cid, 0.0) + rrf_contribution

                if cid not in items:
                    items[cid] = result
                    strategies_map[cid] = []
                strategies_map[cid].append(strategy_name)

        merged: list[RetrievalResult] = []
        for cid, score in scores.items():
            item = items[cid]
            merged.append(
                RetrievalResult(
                    content_id=cid,
                    content_type=item.content_type,
                    content=item.content,
                    rrf_score=score,
                    strategies=strategies_map[cid],
                    graph_path=item.graph_path,
                    similarity_score=item.similarity_score,
                    tier=item.tier,
                    metadata=item.metadata,
                )
            )

        merged.sort(key=lambda r: r.rrf_score, reverse=True)
        if top_k is not None:
            merged = merged[:top_k]
        return merged


class HybridRetriever:
    """Combines graph traversal, semantic search, and keyword search."""

    def __init__(
        self,
        db: Database,
        graph: MemoryGraph,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._db = db
        self._graph = graph
        self._embeddings = embedding_provider

    async def retrieve(self, query: HybridRetrievalQuery) -> list[RetrievalResult]:
        strategy_results: dict[str, list[RetrievalResult]] = {}

        if query.seed_node_ids:
            graph_results = await self._graph_retrieve(query)
            if graph_results:
                strategy_results["graph"] = graph_results

        semantic_results = await self._semantic_retrieve(query)
        if semantic_results:
            strategy_results["semantic"] = semantic_results

        keyword_results = await self._keyword_retrieve(query)
        if keyword_results:
            strategy_results["keyword"] = keyword_results

        weights = {
            "graph": query.graph_weight,
            "semantic": query.semantic_weight,
            "keyword": query.keyword_weight,
        }
        return RRFMerger.merge(strategy_results, weights, k=60, top_k=query.final_top_k)

    async def _graph_retrieve(self, query: HybridRetrievalQuery) -> list[RetrievalResult]:
        results: list[RetrievalResult] = []
        for seed_id in query.seed_node_ids:
            paths = await self._graph.traverse(
                seed_id,
                direction="outbound",
                max_depth=query.max_graph_depth,
                min_weight=query.min_edge_weight,
                relation_filter=query.relation_filter,
            )
            for path in paths:
                node = path.terminal_node
                results.append(
                    RetrievalResult(
                        content_id=node.content_id,
                        content_type=node.node_type,
                        content="",
                        rrf_score=0.0,
                        strategies=["graph"],
                        graph_path=[e.id for e in path.edges],
                        metadata=node.metadata,
                    )
                )
        return results

    async def _semantic_retrieve(self, query: HybridRetrievalQuery) -> list[RetrievalResult]:
        embeddings = await self._embeddings.embed([query.query_text])
        if not embeddings:
            return []
        query_vec = embeddings[0]
        vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"

        rows = await self._db.fetchall(
            "SELECT id, content, memory_type, metadata, tier, "
            "1 - (embedding <=> $1::vector) AS similarity "
            "FROM memory_embeddings "
            "WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> $1::vector "
            "LIMIT $2",
            vec_str,
            query.semantic_top_k,
        )
        return [
            RetrievalResult(
                content_id=r["id"],
                content_type=r["memory_type"],
                content=r["content"],
                rrf_score=0.0,
                strategies=["semantic"],
                similarity_score=float(r["similarity"]),
                tier=r["tier"] if r.get("tier") else "full",
                metadata=r["metadata"] if isinstance(r["metadata"], dict) else {},
            )
            for r in rows
        ]

    async def _keyword_retrieve(self, query: HybridRetrievalQuery) -> list[RetrievalResult]:
        safe_query = " & ".join(word for word in query.query_text.split() if word.isalnum())
        if not safe_query:
            return []

        rows = await self._db.fetchall(
            "SELECT id, content, memory_type, metadata, tier, "
            "ts_rank(search_vector, to_tsquery('english', $1)) AS rank "
            "FROM memory_embeddings "
            "WHERE search_vector @@ to_tsquery('english', $1) "
            "ORDER BY rank DESC LIMIT $2",
            safe_query,
            query.keyword_top_k,
        )
        return [
            RetrievalResult(
                content_id=r["id"],
                content_type=r["memory_type"],
                content=r["content"],
                rrf_score=0.0,
                strategies=["keyword"],
                tier=r["tier"] if r.get("tier") else "full",
                metadata=r["metadata"] if isinstance(r["metadata"], dict) else {},
            )
            for r in rows
        ]

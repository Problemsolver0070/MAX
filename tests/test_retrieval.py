"""Tests for hybrid retrieval with RRF fusion."""

from __future__ import annotations

import uuid

from max.memory.models import RetrievalResult
from max.memory.retrieval import RRFMerger


class TestRRFMerger:
    def test_single_strategy(self):
        items = [
            RetrievalResult(
                content_id=uuid.uuid4(),
                content_type="memory",
                content="A",
                rrf_score=0.0,
                strategies=["graph"],
            ),
            RetrievalResult(
                content_id=uuid.uuid4(),
                content_type="memory",
                content="B",
                rrf_score=0.0,
                strategies=["graph"],
            ),
        ]
        merged = RRFMerger.merge(
            {"graph": items},
            weights={"graph": 1.0},
            k=60,
        )
        assert len(merged) == 2
        assert merged[0].rrf_score > merged[1].rrf_score

    def test_multi_strategy_boosts_shared_items(self):
        shared_id = uuid.uuid4()
        graph_results = [
            RetrievalResult(
                content_id=shared_id,
                content_type="memory",
                content="shared",
                rrf_score=0.0,
                strategies=["graph"],
            ),
        ]
        semantic_results = [
            RetrievalResult(
                content_id=shared_id,
                content_type="memory",
                content="shared",
                rrf_score=0.0,
                strategies=["semantic"],
            ),
        ]
        only_graph_id = uuid.uuid4()
        graph_results.append(
            RetrievalResult(
                content_id=only_graph_id,
                content_type="memory",
                content="graph-only",
                rrf_score=0.0,
                strategies=["graph"],
            ),
        )
        merged = RRFMerger.merge(
            {"graph": graph_results, "semantic": semantic_results},
            weights={"graph": 1.0, "semantic": 0.8},
            k=60,
        )
        assert merged[0].content_id == shared_id
        assert "graph" in merged[0].strategies
        assert "semantic" in merged[0].strategies

    def test_deduplication(self):
        dup_id = uuid.uuid4()
        results = {
            "graph": [
                RetrievalResult(
                    content_id=dup_id,
                    content_type="memory",
                    content="same",
                    rrf_score=0.0,
                    strategies=["graph"],
                ),
            ],
            "semantic": [
                RetrievalResult(
                    content_id=dup_id,
                    content_type="memory",
                    content="same",
                    rrf_score=0.0,
                    strategies=["semantic"],
                ),
            ],
        }
        merged = RRFMerger.merge(results, weights={"graph": 1.0, "semantic": 0.8}, k=60)
        assert len(merged) == 1

    def test_top_k_limit(self):
        items = [
            RetrievalResult(
                content_id=uuid.uuid4(),
                content_type="memory",
                content=f"item-{i}",
                rrf_score=0.0,
                strategies=["graph"],
            )
            for i in range(20)
        ]
        merged = RRFMerger.merge(
            {"graph": items},
            weights={"graph": 1.0},
            k=60,
            top_k=5,
        )
        assert len(merged) == 5

    def test_empty_input(self):
        merged = RRFMerger.merge({}, weights={}, k=60)
        assert merged == []

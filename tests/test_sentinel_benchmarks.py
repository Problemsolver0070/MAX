"""Tests for BenchmarkRegistry -- fixed benchmark suite definitions."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from max.sentinel.benchmarks import BENCHMARKS, BenchmarkRegistry
from max.sentinel.models import Benchmark


class TestBenchmarkDefinitions:
    def test_has_28_benchmarks(self):
        assert len(BENCHMARKS) == 28

    def test_all_are_benchmark_instances(self):
        for b in BENCHMARKS:
            assert isinstance(b, Benchmark)

    def test_all_have_unique_names(self):
        names = [b.name for b in BENCHMARKS]
        assert len(names) == len(set(names))

    def test_all_categories_covered(self):
        categories = {b.category for b in BENCHMARKS}
        expected = {
            "memory_retrieval",
            "planning",
            "communication",
            "tool_selection",
            "audit_quality",
            "security",
            "orchestration",
        }
        assert categories == expected

    def test_four_benchmarks_per_category(self):
        from collections import Counter
        counts = Counter(b.category for b in BENCHMARKS)
        for cat, count in counts.items():
            assert count == 4, f"{cat} has {count} benchmarks, expected 4"

    def test_all_have_evaluation_criteria(self):
        for b in BENCHMARKS:
            assert len(b.evaluation_criteria) >= 1, f"{b.name} has no criteria"

    def test_all_have_scenario(self):
        for b in BENCHMARKS:
            assert b.scenario, f"{b.name} has empty scenario"

    def test_all_have_description(self):
        for b in BENCHMARKS:
            assert b.description, f"{b.name} has empty description"


class TestBenchmarkRegistry:
    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.create_benchmark = AsyncMock()
        store.get_benchmarks = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def registry(self):
        return BenchmarkRegistry()

    @pytest.mark.asyncio
    async def test_seed_benchmarks(self, registry, mock_store):
        await registry.seed(mock_store)
        assert mock_store.create_benchmark.call_count == 28

    @pytest.mark.asyncio
    async def test_seed_passes_correct_data(self, registry, mock_store):
        await registry.seed(mock_store)
        first_call = mock_store.create_benchmark.call_args_list[0]
        benchmark_dict = first_call[0][0]
        assert "name" in benchmark_dict
        assert "category" in benchmark_dict
        assert "scenario" in benchmark_dict
        assert "evaluation_criteria" in benchmark_dict

    @pytest.mark.asyncio
    async def test_get_all(self, registry, mock_store):
        mock_store.get_benchmarks.return_value = [
            {"id": uuid.uuid4(), "name": "b1", "category": "planning"}
        ]
        results = await registry.get_all(mock_store)
        assert len(results) == 1
        mock_store.get_benchmarks.assert_called_once_with(active_only=True)

    @pytest.mark.asyncio
    async def test_get_by_category(self, registry, mock_store):
        await registry.get_by_category(mock_store, "security")
        mock_store.get_benchmarks.assert_called_once_with(
            active_only=True, category="security"
        )

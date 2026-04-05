"""Tests for SentinelAgent -- bus integration and scheduled monitoring."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from max.sentinel.agent import SentinelAgent


@pytest.fixture
def mock_bus():
    bus = AsyncMock()
    bus.subscribe = AsyncMock()
    bus.unsubscribe = AsyncMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_scorer():
    scorer = AsyncMock()
    scorer.run_baseline = AsyncMock(return_value=uuid.uuid4())
    scorer.run_candidate = AsyncMock(return_value=uuid.uuid4())
    scorer.run_scheduled = AsyncMock(return_value=uuid.uuid4())
    scorer.compare_and_verdict = AsyncMock()
    return scorer


@pytest.fixture
def mock_registry():
    registry = AsyncMock()
    registry.seed = AsyncMock()
    return registry


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.get_capability_scores = AsyncMock(return_value=[])
    return store


@pytest.fixture
def agent(mock_bus, mock_scorer, mock_registry, mock_store):
    return SentinelAgent(
        bus=mock_bus,
        scorer=mock_scorer,
        registry=mock_registry,
        store=mock_store,
    )


class TestStart:
    @pytest.mark.asyncio
    async def test_subscribes_to_bus(self, agent, mock_bus):
        await agent.start()
        assert mock_bus.subscribe.call_count >= 1
        channels = [call[0][0] for call in mock_bus.subscribe.call_args_list]
        assert "sentinel.run_request" in channels

    @pytest.mark.asyncio
    async def test_seeds_benchmarks(self, agent, mock_registry):
        await agent.start()
        mock_registry.seed.assert_called_once()


class TestStop:
    @pytest.mark.asyncio
    async def test_unsubscribes(self, agent, mock_bus):
        await agent.start()
        await agent.stop()
        assert mock_bus.unsubscribe.call_count >= 1


class TestOnRunRequest:
    @pytest.mark.asyncio
    async def test_baseline_request(self, agent, mock_scorer, mock_bus):
        exp_id = uuid.uuid4()
        await agent._on_run_request(
            "sentinel.run_request",
            {
                "experiment_id": str(exp_id),
                "run_type": "baseline",
            },
        )
        mock_scorer.run_baseline.assert_called_once_with(exp_id)
        mock_bus.publish.assert_called()

    @pytest.mark.asyncio
    async def test_candidate_request(self, agent, mock_scorer, mock_bus):
        exp_id = uuid.uuid4()
        await agent._on_run_request(
            "sentinel.run_request",
            {
                "experiment_id": str(exp_id),
                "run_type": "candidate",
            },
        )
        mock_scorer.run_candidate.assert_called_once_with(exp_id)

    @pytest.mark.asyncio
    async def test_error_handling(self, agent, mock_scorer, mock_bus):
        mock_scorer.run_baseline.side_effect = Exception("Error")
        await agent._on_run_request(
            "sentinel.run_request",
            {
                "experiment_id": str(uuid.uuid4()),
                "run_type": "baseline",
            },
        )
        # Should not raise, just log


class TestRunScheduled:
    @pytest.mark.asyncio
    async def test_scheduled_run(self, agent, mock_scorer, mock_bus, mock_store):
        mock_store.get_capability_scores.return_value = [
            {"capability": "planning", "aggregate_score": 0.88, "test_count": 4},
        ]
        await agent.run_scheduled_monitoring()
        mock_scorer.run_scheduled.assert_called_once()
        mock_bus.publish.assert_called()

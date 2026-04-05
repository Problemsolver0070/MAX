"""Tests for Scout Agents -- discover evolution proposals via LLM analysis."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from max.evolution.scouts import (
    MAX_PROPOSALS_PER_SCOUT,
    BaseScout,
    EcosystemScout,
    PatternScout,
    QualityScout,
    ToolScout,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_llm_response(proposals: list[dict]) -> AsyncMock:
    """Create a mock LLM that returns a JSON proposals array."""
    resp = AsyncMock()
    resp.text = json.dumps({"proposals": proposals})
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=resp)
    return llm


def _make_proposal_dict(
    description: str = "Improve X",
    target_type: str = "prompt",
    target_id: str = "worker",
    impact_score: float = 0.7,
    effort_score: float = 0.3,
    risk_score: float = 0.1,
) -> dict:
    return {
        "description": description,
        "target_type": target_type,
        "target_id": target_id,
        "impact_score": impact_score,
        "effort_score": effort_score,
        "risk_score": risk_score,
    }


def _failing_llm() -> AsyncMock:
    """Create a mock LLM that raises on complete."""
    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=Exception("LLM down"))
    return llm


@pytest.fixture
def mock_evo_store():
    store = AsyncMock()
    store.get_all_tool_configs = AsyncMock(return_value={"shell": {"timeout": 30}})
    store.get_all_prompts = AsyncMock(return_value={"worker": "You are a worker."})
    return store


@pytest.fixture
def mock_metrics():
    baseline = AsyncMock()
    baseline.mean = 0.85
    metrics = AsyncMock()
    metrics.get_baseline = AsyncMock(return_value=baseline)
    return metrics


@pytest.fixture
def mock_quality_store():
    store = AsyncMock()
    store.get_patterns = AsyncMock(return_value=[
        {"pattern": "Always validate input", "reinforcement_count": 5},
    ])
    store.get_quality_pulse = AsyncMock(return_value={
        "pass_rate": 0.92,
        "avg_score": 0.88,
        "active_rules_count": 3,
        "top_patterns": [],
    })
    store.get_active_rules = AsyncMock(return_value=[
        {"id": str(uuid.uuid4()), "rule": "No raw SQL", "category": "security"},
    ])
    return store


# ── BaseScout ────────────────────────────────────────────────────────────────


class TestBaseScout:
    def test_cannot_instantiate_directly(self):
        """BaseScout is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseScout(AsyncMock())  # type: ignore[abstract]

    def test_parse_json_strips_markdown_fences(self):
        """_parse_json should handle markdown code fences."""
        text = '```json\n{"key": "value"}\n```'
        result = BaseScout._parse_json(text)
        assert result == {"key": "value"}

    def test_parse_json_plain(self):
        """_parse_json should handle plain JSON."""
        text = '{"key": "value"}'
        result = BaseScout._parse_json(text)
        assert result == {"key": "value"}

    def test_parse_json_invalid_returns_empty(self):
        """_parse_json should return empty dict on invalid JSON."""
        result = BaseScout._parse_json("not json at all")
        assert result == {}


# ── ToolScout ────────────────────────────────────────────────────────────────


class TestToolScout:
    async def test_discovers_proposals(self, mock_evo_store, mock_metrics):
        proposals_data = [_make_proposal_dict(target_type="tool_config", target_id="shell")]
        llm = _make_llm_response(proposals_data)
        scout = ToolScout(llm, mock_metrics, mock_evo_store)

        results = await scout.discover()

        assert len(results) == 1
        assert results[0].scout_type == "tool"
        assert results[0].target_type == "tool_config"
        assert results[0].target_id == "shell"

    async def test_scout_type_is_tool(self, mock_evo_store, mock_metrics):
        llm = _make_llm_response([])
        scout = ToolScout(llm, mock_metrics, mock_evo_store)
        assert scout.scout_type == "tool"

    async def test_returns_empty_on_llm_failure(self, mock_evo_store, mock_metrics):
        llm = _failing_llm()
        scout = ToolScout(llm, mock_metrics, mock_evo_store)

        results = await scout.discover()

        assert results == []

    async def test_proposals_capped(self, mock_evo_store, mock_metrics):
        proposals_data = [_make_proposal_dict(description=f"P{i}") for i in range(10)]
        llm = _make_llm_response(proposals_data)
        scout = ToolScout(llm, mock_metrics, mock_evo_store)

        results = await scout.discover()

        assert len(results) == MAX_PROPOSALS_PER_SCOUT

    async def test_calls_llm_with_tool_configs(self, mock_evo_store, mock_metrics):
        llm = _make_llm_response([])
        scout = ToolScout(llm, mock_metrics, mock_evo_store)

        await scout.discover()

        llm.complete.assert_called_once()
        call_kwargs = llm.complete.call_args
        messages = call_kwargs[1].get("messages") or call_kwargs[0][0]
        # The user message should contain tool config info
        user_content = messages[-1]["content"]
        assert "shell" in user_content


# ── PatternScout ─────────────────────────────────────────────────────────────


class TestPatternScout:
    async def test_discovers_proposals(self, mock_quality_store, mock_evo_store):
        proposals_data = [_make_proposal_dict(target_type="prompt", target_id="planner")]
        llm = _make_llm_response(proposals_data)
        scout = PatternScout(llm, mock_quality_store, mock_evo_store)

        results = await scout.discover()

        assert len(results) == 1
        assert results[0].scout_type == "pattern"

    async def test_scout_type_is_pattern(self, mock_quality_store, mock_evo_store):
        llm = _make_llm_response([])
        scout = PatternScout(llm, mock_quality_store, mock_evo_store)
        assert scout.scout_type == "pattern"

    async def test_returns_empty_on_llm_failure(self, mock_quality_store, mock_evo_store):
        llm = _failing_llm()
        scout = PatternScout(llm, mock_quality_store, mock_evo_store)

        results = await scout.discover()

        assert results == []

    async def test_proposals_capped(self, mock_quality_store, mock_evo_store):
        proposals_data = [_make_proposal_dict(description=f"P{i}") for i in range(5)]
        llm = _make_llm_response(proposals_data)
        scout = PatternScout(llm, mock_quality_store, mock_evo_store)

        results = await scout.discover()

        assert len(results) == MAX_PROPOSALS_PER_SCOUT


# ── QualityScout ─────────────────────────────────────────────────────────────


class TestQualityScout:
    async def test_discovers_proposals(self, mock_quality_store, mock_evo_store):
        proposals_data = [_make_proposal_dict(description="Fix recurring timeout")]
        llm = _make_llm_response(proposals_data)
        scout = QualityScout(llm, mock_quality_store, mock_evo_store)

        results = await scout.discover()

        assert len(results) == 1
        assert results[0].scout_type == "quality"

    async def test_scout_type_is_quality(self, mock_quality_store, mock_evo_store):
        llm = _make_llm_response([])
        scout = QualityScout(llm, mock_quality_store, mock_evo_store)
        assert scout.scout_type == "quality"

    async def test_returns_empty_on_llm_failure(self, mock_quality_store, mock_evo_store):
        llm = _failing_llm()
        scout = QualityScout(llm, mock_quality_store, mock_evo_store)

        results = await scout.discover()

        assert results == []

    async def test_proposals_capped(self, mock_quality_store, mock_evo_store):
        proposals_data = [_make_proposal_dict(description=f"P{i}") for i in range(6)]
        llm = _make_llm_response(proposals_data)
        scout = QualityScout(llm, mock_quality_store, mock_evo_store)

        results = await scout.discover()

        assert len(results) == MAX_PROPOSALS_PER_SCOUT


# ── EcosystemScout ───────────────────────────────────────────────────────────


class TestEcosystemScout:
    async def test_discovers_proposals(self, mock_evo_store):
        proposals_data = [_make_proposal_dict(description="Combine shell tools")]
        llm = _make_llm_response(proposals_data)
        scout = EcosystemScout(llm, mock_evo_store)

        results = await scout.discover()

        assert len(results) == 1
        assert results[0].scout_type == "ecosystem"

    async def test_scout_type_is_ecosystem(self, mock_evo_store):
        llm = _make_llm_response([])
        scout = EcosystemScout(llm, mock_evo_store)
        assert scout.scout_type == "ecosystem"

    async def test_returns_empty_on_llm_failure(self, mock_evo_store):
        llm = _failing_llm()
        scout = EcosystemScout(llm, mock_evo_store)

        results = await scout.discover()

        assert results == []

    async def test_proposals_capped(self, mock_evo_store):
        proposals_data = [_make_proposal_dict(description=f"P{i}") for i in range(7)]
        llm = _make_llm_response(proposals_data)
        scout = EcosystemScout(llm, mock_evo_store)

        results = await scout.discover()

        assert len(results) == MAX_PROPOSALS_PER_SCOUT


# ── LLM Response Parsing Edge Cases ─────────────────────────────────────────


class TestParsingEdgeCases:
    async def test_markdown_fenced_response(self, mock_evo_store, mock_metrics):
        """Scout should handle LLM wrapping JSON in markdown fences."""
        proposals_data = [_make_proposal_dict()]
        resp = AsyncMock()
        resp.text = '```json\n' + json.dumps({"proposals": proposals_data}) + '\n```'
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=resp)

        scout = ToolScout(llm, mock_metrics, mock_evo_store)
        results = await scout.discover()

        assert len(results) == 1

    async def test_empty_proposals_array(self, mock_evo_store, mock_metrics):
        """Scout should handle empty proposals array gracefully."""
        llm = _make_llm_response([])
        scout = ToolScout(llm, mock_metrics, mock_evo_store)

        results = await scout.discover()

        assert results == []

    async def test_invalid_json_returns_empty(self, mock_evo_store, mock_metrics):
        """Scout should return empty list when LLM returns invalid JSON."""
        resp = AsyncMock()
        resp.text = "I'm sorry, I can't do that."
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=resp)

        scout = ToolScout(llm, mock_metrics, mock_evo_store)
        results = await scout.discover()

        assert results == []

    async def test_score_clamping(self, mock_evo_store, mock_metrics):
        """Scores outside 0-1 should be clamped."""
        proposals_data = [_make_proposal_dict(impact_score=1.5, risk_score=-0.3)]
        llm = _make_llm_response(proposals_data)
        scout = ToolScout(llm, mock_metrics, mock_evo_store)

        results = await scout.discover()

        assert len(results) == 1
        assert 0.0 <= results[0].impact_score <= 1.0
        assert 0.0 <= results[0].risk_score <= 1.0

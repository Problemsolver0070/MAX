"""Tests for RuleEngine -- rule extraction, supersession, pattern extraction."""

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from max.llm.models import LLMResponse
from max.quality.rules import RuleEngine


def _make_llm_response(data: dict | str) -> LLMResponse:
    text = json.dumps(data) if isinstance(data, dict) else data
    return LLMResponse(
        text=text,
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.create_rule = AsyncMock()
    store.record_rule_to_ledger = AsyncMock()
    store.get_active_rules = AsyncMock(return_value=[])
    store.supersede_rule = AsyncMock()
    store.create_pattern = AsyncMock()
    store.record_pattern_to_ledger = AsyncMock()
    return store


class TestExtractRules:
    @pytest.mark.asyncio
    async def test_extracts_rules_from_failure(self, mock_store):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "rules": [
                        {
                            "rule": "Always validate user input",
                            "category": "validation",
                            "severity": "high",
                        }
                    ]
                }
            )
        )
        engine = RuleEngine(llm=llm, quality_store=mock_store)
        rules = await engine.extract_rules(
            audit_id=uuid.uuid4(),
            issues=[{"category": "validation", "description": "No input validation"}],
            subtask_description="Build user form",
            output_content="def form(): pass",
        )
        assert len(rules) == 1
        assert rules[0]["rule"] == "Always validate user input"
        mock_store.create_rule.assert_called_once()
        mock_store.record_rule_to_ledger.assert_called_once()

    @pytest.mark.asyncio
    async def test_caps_rules_at_max(self, mock_store):
        llm = AsyncMock()
        many_rules = [
            {"rule": f"Rule {i}", "category": "test", "severity": "normal"}
            for i in range(10)
        ]
        llm.complete = AsyncMock(
            return_value=_make_llm_response({"rules": many_rules})
        )
        engine = RuleEngine(llm=llm, quality_store=mock_store, max_rules_per_audit=3)
        rules = await engine.extract_rules(
            audit_id=uuid.uuid4(),
            issues=[{"category": "test", "description": "test"}],
            subtask_description="test",
            output_content="test",
        )
        assert len(rules) == 3

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self, mock_store):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("LLM error"))
        engine = RuleEngine(llm=llm, quality_store=mock_store)
        rules = await engine.extract_rules(
            audit_id=uuid.uuid4(),
            issues=[{"category": "test", "description": "test issue"}],
            subtask_description="test",
            output_content="test",
        )
        assert rules == []


class TestExtractPatterns:
    @pytest.mark.asyncio
    async def test_extracts_pattern_from_success(self, mock_store):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "patterns": [
                        {
                            "pattern": "Uses structured error handling",
                            "category": "code_quality",
                        }
                    ]
                }
            )
        )
        engine = RuleEngine(llm=llm, quality_store=mock_store)
        patterns = await engine.extract_patterns(
            task_id=uuid.uuid4(),
            strengths=["Good error handling"],
            subtask_description="Build API",
            output_content="def api(): try: ... except: ...",
        )
        assert len(patterns) == 1
        mock_store.create_pattern.assert_called_once()
        mock_store.record_pattern_to_ledger.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self, mock_store):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("fail"))
        engine = RuleEngine(llm=llm, quality_store=mock_store)
        patterns = await engine.extract_patterns(
            task_id=uuid.uuid4(),
            strengths=["something"],
            subtask_description="test",
            output_content="test",
        )
        assert patterns == []


class TestGetRulesForAudit:
    @pytest.mark.asyncio
    async def test_returns_active_rules(self, mock_store):
        mock_store.get_active_rules.return_value = [
            {
                "id": str(uuid.uuid4()),
                "rule": "Validate input",
                "category": "validation",
            }
        ]
        engine = RuleEngine(llm=AsyncMock(), quality_store=mock_store)
        rules = await engine.get_rules_for_audit()
        assert len(rules) == 1

    @pytest.mark.asyncio
    async def test_filters_by_category(self, mock_store):
        engine = RuleEngine(llm=AsyncMock(), quality_store=mock_store)
        await engine.get_rules_for_audit(category="validation")
        mock_store.get_active_rules.assert_called_with(category="validation")

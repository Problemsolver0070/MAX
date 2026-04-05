"""Tests for AuditorAgent — blind audit of subtask outputs."""

import json
from unittest.mock import AsyncMock

import pytest

from max.llm.models import LLMResponse
from max.quality.auditor import AUDITOR_SYSTEM_PROMPT_TEMPLATE, AuditorAgent


def _make_llm_response(data: dict | str) -> LLMResponse:
    text = json.dumps(data) if isinstance(data, dict) else data
    return LLMResponse(
        text=text,
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


class TestAuditorRun:
    @pytest.mark.asyncio
    async def test_pass_verdict(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "verdict": "pass",
                    "score": 0.85,
                    "goal_alignment": 0.9,
                    "confidence": 0.95,
                    "issues": [],
                    "fix_instructions": None,
                    "strengths": ["Clear structure"],
                    "reasoning": "Good work",
                }
            )
        )
        auditor = AuditorAgent(llm=llm)
        result = await auditor.run(
            {
                "goal_anchor": "Deploy the app",
                "subtask_description": "Write deploy script",
                "content": "#!/bin/bash\nset -e\ndeploy.sh",
                "quality_criteria": {},
                "quality_rules": [],
            }
        )
        assert result["verdict"] == "pass"
        assert result["score"] == 0.85

    @pytest.mark.asyncio
    async def test_fail_verdict(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "verdict": "fail",
                    "score": 0.3,
                    "goal_alignment": 0.4,
                    "confidence": 0.9,
                    "issues": [
                        {"category": "completeness", "description": "Missing error handling"}
                    ],
                    "fix_instructions": "Add try/except blocks",
                    "strengths": [],
                    "reasoning": "Incomplete",
                }
            )
        )
        auditor = AuditorAgent(llm=llm)
        result = await auditor.run(
            {
                "goal_anchor": "Build API",
                "subtask_description": "Write endpoints",
                "content": "def get(): pass",
                "quality_criteria": {"completeness": "Must handle errors"},
                "quality_rules": [{"rule": "Always handle exceptions"}],
            }
        )
        assert result["verdict"] == "fail"
        assert result["fix_instructions"] == "Add try/except blocks"

    @pytest.mark.asyncio
    async def test_markdown_json_response(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response(
                '```json\n{"verdict": "pass", "score": 0.8, "goal_alignment": 0.85, '
                '"confidence": 0.9, "issues": [], "fix_instructions": null, '
                '"strengths": [], "reasoning": "ok"}\n```'
            )
        )
        auditor = AuditorAgent(llm=llm)
        result = await auditor.run(
            {
                "goal_anchor": "Test",
                "subtask_description": "Test",
                "content": "output",
                "quality_criteria": {},
                "quality_rules": [],
            }
        )
        assert result["verdict"] == "pass"

    @pytest.mark.asyncio
    async def test_unparseable_response_returns_conditional(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(
            return_value=_make_llm_response("I cannot parse this as JSON at all")
        )
        auditor = AuditorAgent(llm=llm)
        result = await auditor.run(
            {
                "goal_anchor": "Test",
                "subtask_description": "Test",
                "content": "output",
                "quality_criteria": {},
                "quality_rules": [],
            }
        )
        assert result["verdict"] == "conditional"
        assert result["confidence"] == 0.3

    @pytest.mark.asyncio
    async def test_exception_returns_conditional(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("LLM down"))
        auditor = AuditorAgent(llm=llm)
        result = await auditor.run(
            {
                "goal_anchor": "Test",
                "subtask_description": "Test",
                "content": "output",
                "quality_criteria": {},
                "quality_rules": [],
            }
        )
        assert result["verdict"] == "conditional"
        assert "LLM down" in result.get("error", "")


class TestAuditorPrompt:
    def test_prompt_template_has_required_placeholders(self):
        assert "{goal_anchor}" in AUDITOR_SYSTEM_PROMPT_TEMPLATE
        assert "{subtask_description}" in AUDITOR_SYSTEM_PROMPT_TEMPLATE
        assert "{quality_criteria}" in AUDITOR_SYSTEM_PROMPT_TEMPLATE
        assert "{quality_rules}" in AUDITOR_SYSTEM_PROMPT_TEMPLATE

    def test_prompt_does_not_contain_reasoning(self):
        """The auditor prompt must not ask for the worker's reasoning (blind audit)."""
        assert "worker reasoning" not in AUDITOR_SYSTEM_PROMPT_TEMPLATE.lower()
        assert "worker confidence" not in AUDITOR_SYSTEM_PROMPT_TEMPLATE.lower()

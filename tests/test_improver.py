"""Tests for ImprovementAgent -- implement evolution proposals as change sets."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from max.evolution.improver import MAX_CHANGES, ImprovementAgent
from max.evolution.models import EvolutionProposal

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_proposal(
    target_type: str = "prompt",
    target_id: str = "worker",
    description: str = "Improve worker prompt for clarity",
) -> EvolutionProposal:
    return EvolutionProposal(
        scout_type="tool",
        description=description,
        target_type=target_type,
        target_id=target_id,
        impact_score=0.8,
        effort_score=0.3,
        risk_score=0.1,
    )


def _make_llm_response(changes: list[dict]) -> AsyncMock:
    """Create a mock LLM that returns a JSON changes array."""
    resp = AsyncMock()
    resp.text = json.dumps({"changes": changes})
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=resp)
    return llm


def _make_change_dict(
    target_type: str = "prompt",
    target_id: str = "worker",
    new_value: str = "You are an improved worker agent.",
) -> dict:
    return {
        "target_type": target_type,
        "target_id": target_id,
        "new_value": new_value,
    }


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.get_prompt = AsyncMock(return_value="You are a worker.")
    store.get_tool_config = AsyncMock(return_value={"timeout": 30})
    store.set_prompt = AsyncMock()
    store.set_tool_config = AsyncMock()
    return store


# ── Prompt Changes ───────────────────────────────────────────────────────────


class TestPromptChange:
    async def test_implements_prompt_change(self, mock_store):
        changes = [_make_change_dict()]
        llm = _make_llm_response(changes)
        agent = ImprovementAgent(llm, mock_store)
        proposal = _make_proposal()

        changeset = await agent.implement(proposal)

        assert len(changeset.entries) == 1
        assert changeset.entries[0].target_type == "prompt"
        assert changeset.entries[0].target_id == "worker"
        assert changeset.entries[0].new_value == "You are an improved worker agent."
        assert changeset.entries[0].old_value == "You are a worker."
        assert changeset.proposal_id == proposal.id

    async def test_writes_candidate_to_store(self, mock_store):
        changes = [_make_change_dict()]
        llm = _make_llm_response(changes)
        agent = ImprovementAgent(llm, mock_store)
        proposal = _make_proposal()

        await agent.implement(proposal)

        # set_prompt should be called with experiment_id
        mock_store.set_prompt.assert_called_once()
        call_args = mock_store.set_prompt.call_args
        assert call_args[0][0] == "worker"  # agent_type
        assert call_args[0][1] == "You are an improved worker agent."  # text
        assert call_args[1].get("experiment_id") is not None or call_args[0][2] is not None

    async def test_gets_current_prompt_value(self, mock_store):
        changes = [_make_change_dict()]
        llm = _make_llm_response(changes)
        agent = ImprovementAgent(llm, mock_store)
        proposal = _make_proposal()

        await agent.implement(proposal)

        # Called once for proposal target, once for the change entry
        mock_store.get_prompt.assert_any_call("worker")
        assert mock_store.get_prompt.call_count >= 1


# ── Tool Config Changes ──────────────────────────────────────────────────────


class TestToolConfigChange:
    async def test_implements_tool_config_change(self, mock_store):
        new_config = {"timeout": 60, "retries": 3}
        changes = [_make_change_dict(
            target_type="tool_config",
            target_id="shell",
            new_value=new_config,
        )]
        llm = _make_llm_response(changes)
        agent = ImprovementAgent(llm, mock_store)
        proposal = _make_proposal(target_type="tool_config", target_id="shell")

        changeset = await agent.implement(proposal)

        assert len(changeset.entries) == 1
        assert changeset.entries[0].target_type == "tool_config"
        assert changeset.entries[0].target_id == "shell"
        assert changeset.entries[0].new_value == new_config
        assert changeset.entries[0].old_value == {"timeout": 30}

    async def test_writes_candidate_tool_config(self, mock_store):
        new_config = {"timeout": 60}
        changes = [_make_change_dict(
            target_type="tool_config",
            target_id="shell",
            new_value=new_config,
        )]
        llm = _make_llm_response(changes)
        agent = ImprovementAgent(llm, mock_store)
        proposal = _make_proposal(target_type="tool_config", target_id="shell")

        await agent.implement(proposal)

        mock_store.set_tool_config.assert_called_once()

    async def test_gets_current_tool_config(self, mock_store):
        changes = [_make_change_dict(
            target_type="tool_config",
            target_id="shell",
            new_value={"timeout": 60},
        )]
        llm = _make_llm_response(changes)
        agent = ImprovementAgent(llm, mock_store)
        proposal = _make_proposal(target_type="tool_config", target_id="shell")

        await agent.implement(proposal)

        # Called once for proposal target, once for the change entry
        mock_store.get_tool_config.assert_any_call("shell")
        assert mock_store.get_tool_config.call_count >= 1


# ── Error Handling ───────────────────────────────────────────────────────────


class TestErrorHandling:
    async def test_returns_empty_changeset_on_llm_failure(self, mock_store):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=Exception("LLM down"))
        agent = ImprovementAgent(llm, mock_store)
        proposal = _make_proposal()

        changeset = await agent.implement(proposal)

        assert len(changeset.entries) == 0
        assert changeset.proposal_id == proposal.id

    async def test_returns_empty_changeset_on_invalid_json(self, mock_store):
        resp = AsyncMock()
        resp.text = "I'm sorry, I cannot help with that."
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=resp)
        agent = ImprovementAgent(llm, mock_store)
        proposal = _make_proposal()

        changeset = await agent.implement(proposal)

        assert len(changeset.entries) == 0

    async def test_returns_empty_changeset_on_missing_changes_key(self, mock_store):
        resp = AsyncMock()
        resp.text = json.dumps({"something_else": []})
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=resp)
        agent = ImprovementAgent(llm, mock_store)
        proposal = _make_proposal()

        changeset = await agent.implement(proposal)

        assert len(changeset.entries) == 0


# ── Caps and Limits ──────────────────────────────────────────────────────────


class TestLimits:
    async def test_changes_capped_at_max(self, mock_store):
        changes = [_make_change_dict(target_id=f"agent_{i}") for i in range(10)]
        llm = _make_llm_response(changes)
        agent = ImprovementAgent(llm, mock_store)
        proposal = _make_proposal()

        changeset = await agent.implement(proposal)

        assert len(changeset.entries) == MAX_CHANGES

    async def test_multiple_changes_all_applied(self, mock_store):
        changes = [
            _make_change_dict(target_id="worker", new_value="New worker prompt"),
            _make_change_dict(target_id="planner", new_value="New planner prompt"),
        ]
        llm = _make_llm_response(changes)
        agent = ImprovementAgent(llm, mock_store)
        proposal = _make_proposal()

        changeset = await agent.implement(proposal)

        assert len(changeset.entries) == 2
        target_ids = {e.target_id for e in changeset.entries}
        assert target_ids == {"worker", "planner"}


# ── Markdown Fencing ─────────────────────────────────────────────────────────


class TestMarkdownFencing:
    async def test_handles_fenced_response(self, mock_store):
        changes = [_make_change_dict()]
        resp = AsyncMock()
        resp.text = '```json\n' + json.dumps({"changes": changes}) + '\n```'
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=resp)
        agent = ImprovementAgent(llm, mock_store)
        proposal = _make_proposal()

        changeset = await agent.implement(proposal)

        assert len(changeset.entries) == 1

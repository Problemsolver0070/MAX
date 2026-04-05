"""Tests for PreferenceProfileManager -- user preference learning and injection."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from max.evolution.preference import PreferenceProfileManager


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.get_preference_profile = AsyncMock(return_value=None)
    store.save_preference_profile = AsyncMock()
    return store


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    response = AsyncMock()
    response.text = json.dumps({
        "communication": {"tone": "casual", "detail_level": "verbose"},
        "code": {"review_depth": "thorough"},
        "workflow": {"autonomy_level": "high"},
        "domain_knowledge": {"expertise_areas": ["python"]},
    })
    llm.complete = AsyncMock(return_value=response)
    return llm


@pytest.fixture
def manager(mock_store, mock_llm):
    return PreferenceProfileManager(mock_store, mock_llm)


# ── record_signal ─────────────────────────────────────────────────────────


class TestRecordSignal:
    async def test_creates_profile_if_missing(self, manager, mock_store):
        mock_store.get_preference_profile.return_value = None
        await manager.record_signal("user-1", "tone_correction", {"tone": "casual"})

        mock_store.save_preference_profile.assert_called_once()
        call_args = mock_store.save_preference_profile.call_args
        assert call_args[1]["user_id"] == "user-1"
        # Should have 1 observation
        obs_log = call_args[1]["observation_log"]
        assert len(obs_log) == 1
        assert obs_log[0]["signal_type"] == "tone_correction"

    async def test_appends_to_existing_profile(self, manager, mock_store):
        existing_profile = {
            "user_id": "user-1",
            "communication": {"tone": "professional"},
            "code_prefs": {},
            "workflow": {},
            "domain_knowledge": {},
            "observation_log": json.dumps([
                {"signal_type": "previous", "data": {}, "recorded_at": "2024-01-01T00:00:00Z"}
            ]),
            "version": 1,
        }
        mock_store.get_preference_profile.return_value = existing_profile

        await manager.record_signal("user-1", "new_signal", {"key": "value"})

        call_args = mock_store.save_preference_profile.call_args
        obs_log = call_args[1]["observation_log"]
        assert len(obs_log) == 2
        assert obs_log[0]["signal_type"] == "previous"
        assert obs_log[1]["signal_type"] == "new_signal"

    async def test_observation_log_capped_at_500(self, manager, mock_store):
        # Create profile with 500 existing observations
        existing_obs = [
            {"signal_type": f"signal_{i}", "data": {}, "recorded_at": "2024-01-01T00:00:00Z"}
            for i in range(500)
        ]
        existing_profile = {
            "user_id": "user-1",
            "communication": {},
            "code_prefs": {},
            "workflow": {},
            "domain_knowledge": {},
            "observation_log": json.dumps(existing_obs),
            "version": 1,
        }
        mock_store.get_preference_profile.return_value = existing_profile

        await manager.record_signal("user-1", "overflow_signal", {"overflow": True})

        call_args = mock_store.save_preference_profile.call_args
        obs_log = call_args[1]["observation_log"]
        assert len(obs_log) == 500
        # Oldest should be dropped (FIFO), newest should be present
        assert obs_log[-1]["signal_type"] == "overflow_signal"
        # First item should be signal_1 (signal_0 dropped)
        assert obs_log[0]["signal_type"] == "signal_1"

    async def test_handles_observation_log_as_dict(self, manager, mock_store):
        """When observation_log comes from DB already as a list (not JSON string)."""
        existing_profile = {
            "user_id": "user-1",
            "communication": {},
            "code_prefs": {},
            "workflow": {},
            "domain_knowledge": {},
            "observation_log": [
                {"signal_type": "existing", "data": {}, "recorded_at": "2024-01-01T00:00:00Z"}
            ],
            "version": 1,
        }
        mock_store.get_preference_profile.return_value = existing_profile

        await manager.record_signal("user-1", "new_signal", {"key": "val"})

        call_args = mock_store.save_preference_profile.call_args
        obs_log = call_args[1]["observation_log"]
        assert len(obs_log) == 2


# ── get_profile ───────────────────────────────────────────────────────────


class TestGetProfile:
    async def test_returns_default_for_unknown_user(self, manager, mock_store):
        mock_store.get_preference_profile.return_value = None
        profile = await manager.get_profile("unknown-user")

        assert profile.user_id == "unknown-user"
        assert profile.communication.tone == "professional"
        assert profile.code.review_depth == "thorough"
        assert profile.workflow.autonomy_level == "high"
        assert profile.observation_log == []

    async def test_returns_stored_profile(self, manager, mock_store):
        mock_store.get_preference_profile.return_value = {
            "user_id": "user-1",
            "communication": json.dumps({"tone": "casual", "detail_level": "verbose"}),
            "code_prefs": json.dumps({"review_depth": "light"}),
            "workflow": json.dumps({"autonomy_level": "low"}),
            "domain_knowledge": json.dumps({"expertise_areas": ["rust"]}),
            "observation_log": json.dumps([]),
            "version": 3,
        }
        profile = await manager.get_profile("user-1")

        assert profile.user_id == "user-1"
        assert profile.communication.tone == "casual"
        assert profile.code.review_depth == "light"
        assert profile.workflow.autonomy_level == "low"
        assert profile.domain_knowledge.expertise_areas == ["rust"]

    async def test_handles_fields_as_dicts(self, manager, mock_store):
        """When DB returns fields already parsed as dicts."""
        mock_store.get_preference_profile.return_value = {
            "user_id": "user-1",
            "communication": {"tone": "formal"},
            "code_prefs": {"review_depth": "thorough"},
            "workflow": {"autonomy_level": "medium"},
            "domain_knowledge": {"expertise_areas": []},
            "observation_log": [],
            "version": 1,
        }
        profile = await manager.get_profile("user-1")
        assert profile.communication.tone == "formal"


# ── refresh_profile ───────────────────────────────────────────────────────


class TestRefreshProfile:
    async def test_calls_llm_with_observations(self, manager, mock_store, mock_llm):
        mock_store.get_preference_profile.return_value = {
            "user_id": "user-1",
            "communication": json.dumps({"tone": "professional"}),
            "code_prefs": json.dumps({}),
            "workflow": json.dumps({}),
            "domain_knowledge": json.dumps({}),
            "observation_log": json.dumps([
                {"signal_type": "tone_correction", "data": {"tone": "casual"},
                 "recorded_at": "2024-01-01T00:00:00Z"},
            ]),
            "version": 1,
        }

        profile = await manager.refresh_profile("user-1")
        mock_llm.complete.assert_called_once()

        # Verify the returned profile reflects the LLM's response
        assert profile.communication.tone == "casual"

    async def test_saves_refreshed_profile(self, manager, mock_store, mock_llm):
        mock_store.get_preference_profile.return_value = {
            "user_id": "user-1",
            "communication": json.dumps({}),
            "code_prefs": json.dumps({}),
            "workflow": json.dumps({}),
            "domain_knowledge": json.dumps({}),
            "observation_log": json.dumps([
                {"signal_type": "test", "data": {}, "recorded_at": "2024-01-01T00:00:00Z"},
            ]),
            "version": 1,
        }

        await manager.refresh_profile("user-1")
        mock_store.save_preference_profile.assert_called_once()

    async def test_returns_default_for_unknown_user(self, manager, mock_store, mock_llm):
        mock_store.get_preference_profile.return_value = None

        profile = await manager.refresh_profile("unknown")
        # No observations, so LLM should NOT be called
        mock_llm.complete.assert_not_called()
        assert profile.user_id == "unknown"

    async def test_handles_markdown_fenced_llm_response(self, manager, mock_store, mock_llm):
        """LLM may wrap JSON response in markdown code fences."""
        mock_store.get_preference_profile.return_value = {
            "user_id": "user-1",
            "communication": json.dumps({}),
            "code_prefs": json.dumps({}),
            "workflow": json.dumps({}),
            "domain_knowledge": json.dumps({}),
            "observation_log": json.dumps([
                {"signal_type": "test", "data": {}, "recorded_at": "2024-01-01T00:00:00Z"},
            ]),
            "version": 1,
        }
        response = AsyncMock()
        response.text = '```json\n{"communication": {"tone": "friendly"}}\n```'
        mock_llm.complete.return_value = response

        profile = await manager.refresh_profile("user-1")
        assert profile.communication.tone == "friendly"


# ── get_context_injection ─────────────────────────────────────────────────


class TestGetContextInjection:
    async def test_returns_correct_keys(self, manager, mock_store):
        mock_store.get_preference_profile.return_value = {
            "user_id": "user-1",
            "communication": json.dumps({"tone": "casual", "detail_level": "verbose"}),
            "code_prefs": json.dumps({"review_depth": "thorough"}),
            "workflow": json.dumps({"autonomy_level": "high"}),
            "domain_knowledge": json.dumps({"expertise_areas": ["python"]}),
            "observation_log": json.dumps([]),
            "version": 1,
        }

        injection = await manager.get_context_injection("user-1")

        assert "communication" in injection
        assert "code" in injection
        assert "workflow" in injection
        assert "domain" in injection

    async def test_returns_empty_for_unknown_user(self, manager, mock_store):
        mock_store.get_preference_profile.return_value = None
        injection = await manager.get_context_injection("unknown")

        assert "communication" in injection
        assert "code" in injection
        assert "workflow" in injection
        assert "domain" in injection

    async def test_injection_values_reflect_profile(self, manager, mock_store):
        mock_store.get_preference_profile.return_value = {
            "user_id": "user-1",
            "communication": json.dumps({"tone": "casual"}),
            "code_prefs": json.dumps({"review_depth": "light"}),
            "workflow": json.dumps({"autonomy_level": "low"}),
            "domain_knowledge": json.dumps({"expertise_areas": ["ml"]}),
            "observation_log": json.dumps([]),
            "version": 1,
        }

        injection = await manager.get_context_injection("user-1")
        assert injection["communication"]["tone"] == "casual"
        assert injection["code"]["review_depth"] == "light"
        assert injection["workflow"]["autonomy_level"] == "low"
        assert "ml" in injection["domain"]["expertise_areas"]

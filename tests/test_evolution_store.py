"""Tests for EvolutionStore -- async CRUD for evolution system tables."""

import uuid
from unittest.mock import AsyncMock

import pytest

from max.evolution.store import EvolutionStore


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.fetchone = AsyncMock(return_value=None)
    db.fetchall = AsyncMock(return_value=[])
    return db


@pytest.fixture
def store(mock_db):
    return EvolutionStore(mock_db)


# ── Proposals ──────────────────────────────────────────────────────────────


class TestCreateProposal:
    @pytest.mark.asyncio
    async def test_inserts_proposal(self, store, mock_db):
        proposal = {
            "id": uuid.uuid4(),
            "scout_type": "pattern_scout",
            "description": "Improve error handling",
            "target_type": "prompt",
            "target_id": "worker_agent",
            "impact_score": 0.8,
            "effort_score": 0.3,
            "risk_score": 0.2,
            "priority": 0.7,
            "status": "proposed",
            "experiment_id": None,
        }
        await store.create_proposal(proposal)
        mock_db.execute.assert_called_once()
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO evolution_proposals" in sql

    @pytest.mark.asyncio
    async def test_proposal_with_experiment_id(self, store, mock_db):
        exp_id = uuid.uuid4()
        proposal = {
            "id": uuid.uuid4(),
            "scout_type": "failure_scout",
            "description": "Fix timeout",
            "target_type": "tool_config",
            "target_id": "shell_tool",
            "impact_score": 0.5,
            "effort_score": 0.2,
            "risk_score": 0.1,
            "priority": 0.6,
            "status": "proposed",
            "experiment_id": exp_id,
        }
        await store.create_proposal(proposal)
        args = mock_db.execute.call_args[0]
        assert args[11] == exp_id  # experiment_id is 11th positional arg


class TestGetProposals:
    @pytest.mark.asyncio
    async def test_get_all_proposals(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "status": "proposed", "description": "test"}
        ]
        rows = await store.get_proposals()
        assert len(rows) == 1
        sql = mock_db.fetchall.call_args[0][0]
        assert "SELECT * FROM evolution_proposals" in sql
        assert "WHERE" not in sql

    @pytest.mark.asyncio
    async def test_get_proposals_by_status(self, store, mock_db):
        mock_db.fetchall.return_value = []
        await store.get_proposals(status="approved")
        sql = mock_db.fetchall.call_args[0][0]
        assert "WHERE status = $1" in sql
        assert mock_db.fetchall.call_args[0][1] == "approved"

    @pytest.mark.asyncio
    async def test_returns_empty_list(self, store, mock_db):
        rows = await store.get_proposals()
        assert rows == []


class TestUpdateProposalStatus:
    @pytest.mark.asyncio
    async def test_updates_status(self, store, mock_db):
        pid = uuid.uuid4()
        await store.update_proposal_status(pid, "approved")
        sql = mock_db.execute.call_args[0][0]
        assert "UPDATE evolution_proposals" in sql
        assert "SET status = $1" in sql

    @pytest.mark.asyncio
    async def test_updates_status_with_experiment_id(self, store, mock_db):
        pid = uuid.uuid4()
        exp_id = uuid.uuid4()
        await store.update_proposal_status(pid, "testing", experiment_id=exp_id)
        sql = mock_db.execute.call_args[0][0]
        assert "experiment_id = $2" in sql
        args = mock_db.execute.call_args[0]
        assert args[2] == exp_id


# ── Snapshots ──────────────────────────────────────────────────────────────


class TestCreateSnapshot:
    @pytest.mark.asyncio
    async def test_inserts_snapshot(self, store, mock_db):
        exp_id = uuid.uuid4()
        data = {
            "prompts": {"worker": "do stuff"},
            "tool_configs": {},
            "context_rules": [],
            "metrics_baseline": {"pass_rate": 0.85},
        }
        snap_id = await store.create_snapshot(exp_id, data)
        assert isinstance(snap_id, uuid.UUID)
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO evolution_snapshots" in sql
        assert "$3::jsonb" in sql
        assert "$4::jsonb" in sql


class TestGetSnapshot:
    @pytest.mark.asyncio
    async def test_returns_snapshot(self, store, mock_db):
        mock_db.fetchone.return_value = {
            "id": uuid.uuid4(),
            "snapshot_data": {"prompts": {}},
            "metrics_baseline": {"pass_rate": 0.8},
        }
        result = await store.get_snapshot(uuid.uuid4())
        assert result is not None
        assert "snapshot_data" in result

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self, store, mock_db):
        result = await store.get_snapshot(uuid.uuid4())
        assert result is None


# ── Prompts ────────────────────────────────────────────────────────────────


class TestSetPrompt:
    @pytest.mark.asyncio
    async def test_upserts_live_prompt(self, store, mock_db):
        await store.set_prompt("worker_agent", "You are a helpful worker.")
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO evolution_prompts" in sql
        assert "ON CONFLICT" in sql

    @pytest.mark.asyncio
    async def test_inserts_candidate_prompt(self, store, mock_db):
        exp_id = uuid.uuid4()
        await store.set_prompt("worker_agent", "Improved prompt.", experiment_id=exp_id)
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO evolution_prompts" in sql
        args = mock_db.execute.call_args[0]
        assert args[4] == exp_id  # (sql, id, agent_type, prompt_text, experiment_id)


class TestGetPrompt:
    @pytest.mark.asyncio
    async def test_gets_live_prompt(self, store, mock_db):
        mock_db.fetchone.return_value = {"prompt_text": "Hello world"}
        result = await store.get_prompt("worker_agent")
        assert result == "Hello world"
        sql = mock_db.fetchone.call_args[0][0]
        assert "experiment_id IS NULL" in sql

    @pytest.mark.asyncio
    async def test_gets_candidate_prompt(self, store, mock_db):
        exp_id = uuid.uuid4()
        mock_db.fetchone.return_value = {"prompt_text": "Candidate prompt"}
        result = await store.get_prompt("worker_agent", experiment_id=exp_id)
        assert result == "Candidate prompt"
        sql = mock_db.fetchone.call_args[0][0]
        assert "experiment_id = $2" in sql

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self, store, mock_db):
        result = await store.get_prompt("nonexistent_agent")
        assert result is None


class TestGetAllPrompts:
    @pytest.mark.asyncio
    async def test_gets_all_live_prompts(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"agent_type": "worker", "prompt_text": "p1"},
            {"agent_type": "planner", "prompt_text": "p2"},
        ]
        result = await store.get_all_prompts()
        assert result == {"worker": "p1", "planner": "p2"}

    @pytest.mark.asyncio
    async def test_gets_candidate_prompts(self, store, mock_db):
        exp_id = uuid.uuid4()
        mock_db.fetchall.return_value = [
            {"agent_type": "worker", "prompt_text": "candidate_p"},
        ]
        result = await store.get_all_prompts(experiment_id=exp_id)
        assert result == {"worker": "candidate_p"}


# ── Tool Configs ───────────────────────────────────────────────────────────


class TestSetToolConfig:
    @pytest.mark.asyncio
    async def test_upserts_live_config(self, store, mock_db):
        await store.set_tool_config("shell_tool", {"timeout": 30})
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO evolution_tool_configs" in sql
        assert "ON CONFLICT" in sql

    @pytest.mark.asyncio
    async def test_inserts_candidate_config(self, store, mock_db):
        exp_id = uuid.uuid4()
        await store.set_tool_config("shell_tool", {"timeout": 60}, experiment_id=exp_id)
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO evolution_tool_configs" in sql


class TestGetToolConfig:
    @pytest.mark.asyncio
    async def test_gets_live_config(self, store, mock_db):
        mock_db.fetchone.return_value = {"config": {"timeout": 30}}
        result = await store.get_tool_config("shell_tool")
        assert result == {"timeout": 30}

    @pytest.mark.asyncio
    async def test_gets_candidate_config(self, store, mock_db):
        exp_id = uuid.uuid4()
        mock_db.fetchone.return_value = {"config": {"timeout": 60}}
        result = await store.get_tool_config("shell_tool", experiment_id=exp_id)
        assert result == {"timeout": 60}

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self, store, mock_db):
        result = await store.get_tool_config("nonexistent_tool")
        assert result is None


class TestGetAllToolConfigs:
    @pytest.mark.asyncio
    async def test_gets_all_live_configs(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"tool_id": "shell", "config": {"timeout": 30}},
            {"tool_id": "http", "config": {"timeout": 10}},
        ]
        result = await store.get_all_tool_configs()
        assert result == {"shell": {"timeout": 30}, "http": {"timeout": 10}}

    @pytest.mark.asyncio
    async def test_gets_candidate_configs(self, store, mock_db):
        exp_id = uuid.uuid4()
        mock_db.fetchall.return_value = [
            {"tool_id": "shell", "config": {"timeout": 60}},
        ]
        result = await store.get_all_tool_configs(experiment_id=exp_id)
        assert result == {"shell": {"timeout": 60}}


# ── Promote / Discard ──────────────────────────────────────────────────────


class TestPromoteCandidates:
    @pytest.mark.asyncio
    async def test_promote_calls_delete_and_update(self, store, mock_db):
        exp_id = uuid.uuid4()
        # Setup: mock candidate prompts and configs that exist
        mock_db.fetchall.side_effect = [
            [{"agent_type": "worker"}],  # candidate prompts
            [{"tool_id": "shell"}],  # candidate tool configs
        ]
        await store.promote_candidates(exp_id)
        # Should have multiple execute calls for delete old + update candidate
        assert mock_db.execute.call_count >= 4  # 2 deletes + 2 updates


class TestDiscardCandidates:
    @pytest.mark.asyncio
    async def test_discard_deletes_candidates(self, store, mock_db):
        exp_id = uuid.uuid4()
        await store.discard_candidates(exp_id)
        assert mock_db.execute.call_count == 2  # prompts + tool_configs
        for c in mock_db.execute.call_args_list:
            sql = c[0][0]
            assert "DELETE FROM" in sql
            assert "experiment_id = $1" in sql


# ── Journal ────────────────────────────────────────────────────────────────


class TestRecordJournal:
    @pytest.mark.asyncio
    async def test_inserts_journal_entry(self, store, mock_db):
        entry = {
            "experiment_id": uuid.uuid4(),
            "action": "promote",
            "details": {"score_improvement": 0.05},
        }
        await store.record_journal(entry)
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO evolution_journal" in sql

    @pytest.mark.asyncio
    async def test_journal_entry_without_experiment(self, store, mock_db):
        entry = {
            "experiment_id": None,
            "action": "system_start",
            "details": {},
        }
        await store.record_journal(entry)
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO evolution_journal" in sql


class TestGetJournal:
    @pytest.mark.asyncio
    async def test_gets_recent_entries(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "action": "promote", "details": {}}
        ]
        rows = await store.get_journal(limit=10)
        assert len(rows) == 1
        sql = mock_db.fetchall.call_args[0][0]
        assert "LIMIT $1" in sql

    @pytest.mark.asyncio
    async def test_gets_entries_by_experiment(self, store, mock_db):
        exp_id = uuid.uuid4()
        await store.get_journal(experiment_id=exp_id)
        sql = mock_db.fetchall.call_args[0][0]
        assert "experiment_id = $1" in sql


# ── Preferences ────────────────────────────────────────────────────────────


class TestSavePreferenceProfile:
    @pytest.mark.asyncio
    async def test_upserts_profile(self, store, mock_db):
        await store.save_preference_profile(
            user_id="user_123",
            communication={"tone": "casual"},
            code_prefs={"style": "black"},
            workflow={"autonomy": "high"},
            domain_knowledge={"expertise": ["python"]},
            observation_log=[{"signal": "preference_stated"}],
        )
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO preference_profiles" in sql
        assert "ON CONFLICT (user_id)" in sql
        assert "$3::jsonb" in sql


class TestGetPreferenceProfile:
    @pytest.mark.asyncio
    async def test_returns_profile(self, store, mock_db):
        mock_db.fetchone.return_value = {
            "user_id": "user_123",
            "communication": {"tone": "casual"},
            "code_prefs": {},
            "workflow": {},
            "domain_knowledge": {},
            "observation_log": [],
            "version": 1,
        }
        result = await store.get_preference_profile("user_123")
        assert result is not None
        assert result["user_id"] == "user_123"

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self, store, mock_db):
        result = await store.get_preference_profile("unknown_user")
        assert result is None


# ── Capability Map ─────────────────────────────────────────────────────────


class TestUpsertCapability:
    @pytest.mark.asyncio
    async def test_upserts_capability(self, store, mock_db):
        await store.upsert_capability("python", "refactoring", 0.85, 10)
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO capability_map" in sql
        assert "ON CONFLICT (domain, task_type)" in sql


class TestGetCapabilityMap:
    @pytest.mark.asyncio
    async def test_returns_structured_map(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"domain": "python", "task_type": "refactoring", "score": 0.85},
            {"domain": "python", "task_type": "testing", "score": 0.9},
            {"domain": "javascript", "task_type": "debugging", "score": 0.7},
        ]
        result = await store.get_capability_map()
        assert result == {
            "python": {"refactoring": 0.85, "testing": 0.9},
            "javascript": {"debugging": 0.7},
        }

    @pytest.mark.asyncio
    async def test_returns_empty_map(self, store, mock_db):
        result = await store.get_capability_map()
        assert result == {}


# ── Failure Taxonomy ───────────────────────────────────────────────────────


class TestRecordFailure:
    @pytest.mark.asyncio
    async def test_inserts_failure(self, store, mock_db):
        await store.record_failure(
            category="timeout",
            subcategory="api_call",
            details={"endpoint": "/v1/messages"},
            source_task_id=uuid.uuid4(),
        )
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO failure_taxonomy" in sql

    @pytest.mark.asyncio
    async def test_inserts_failure_without_task(self, store, mock_db):
        await store.record_failure(
            category="validation",
            subcategory="input",
            details={},
        )
        args = mock_db.execute.call_args[0]
        assert args[5] is None  # source_task_id


class TestGetFailureCounts:
    @pytest.mark.asyncio
    async def test_returns_counts(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"category": "timeout", "count": 5},
            {"category": "validation", "count": 3},
        ]
        result = await store.get_failure_counts()
        assert result == {"timeout": 5, "validation": 3}

    @pytest.mark.asyncio
    async def test_returns_empty_dict(self, store, mock_db):
        result = await store.get_failure_counts()
        assert result == {}


# ── Calibration ────────────────────────────────────────────────────────────


class TestRecordPrediction:
    @pytest.mark.asyncio
    async def test_inserts_prediction(self, store, mock_db):
        await store.record_prediction(0.85, 0.78, task_type="refactoring")
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO confidence_calibration" in sql

    @pytest.mark.asyncio
    async def test_inserts_prediction_without_task_type(self, store, mock_db):
        await store.record_prediction(0.9, 0.88)
        args = mock_db.execute.call_args[0]
        assert args[4] is None  # task_type


class TestGetCalibrationError:
    @pytest.mark.asyncio
    async def test_computes_mean_absolute_error(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"predicted_score": 0.9, "actual_score": 0.8},
            {"predicted_score": 0.7, "actual_score": 0.6},
            {"predicted_score": 0.5, "actual_score": 0.7},
        ]
        error = await store.get_calibration_error(limit=100)
        # MAE = (|0.9-0.8| + |0.7-0.6| + |0.5-0.7|) / 3 = (0.1+0.1+0.2)/3 ≈ 0.1333
        assert abs(error - 0.1333) < 0.001

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_data(self, store, mock_db):
        error = await store.get_calibration_error()
        assert error == 0.0

    @pytest.mark.asyncio
    async def test_calibration_with_single_entry(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"predicted_score": 0.8, "actual_score": 0.6},
        ]
        error = await store.get_calibration_error()
        assert abs(error - 0.2) < 0.001


# ── Ledger ─────────────────────────────────────────────────────────────────


class TestRecordToLedger:
    @pytest.mark.asyncio
    async def test_writes_to_quality_ledger(self, store, mock_db):
        await store.record_to_ledger(
            entry_type="evolution_promoted",
            content={"experiment_id": str(uuid.uuid4()), "score": 0.9},
        )
        sql = mock_db.execute.call_args[0][0]
        assert "INSERT INTO quality_ledger" in sql
        args = mock_db.execute.call_args[0]
        assert args[2] == "evolution_promoted"

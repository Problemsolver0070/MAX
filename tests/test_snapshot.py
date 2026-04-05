"""Tests for SnapshotManager -- capture and restore system state."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from max.evolution.snapshot import SnapshotManager


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.get_all_prompts = AsyncMock(return_value={})
    store.get_all_tool_configs = AsyncMock(return_value={})
    store.create_snapshot = AsyncMock(return_value=uuid.uuid4())
    store.get_snapshot = AsyncMock(return_value=None)
    store.set_prompt = AsyncMock()
    store.set_tool_config = AsyncMock()
    return store


@pytest.fixture
def mock_metrics():
    metrics = AsyncMock()
    metrics.get_baseline = AsyncMock(return_value=None)
    return metrics


@pytest.fixture
def manager(mock_store, mock_metrics):
    return SnapshotManager(mock_store, mock_metrics)


# ── Capture ───────────────────────────────────────────────────────────────


class TestCapture:
    async def test_returns_uuid(self, manager, mock_store):
        exp_id = uuid.uuid4()
        snap_id = await manager.capture(exp_id)
        assert isinstance(snap_id, uuid.UUID)

    async def test_collects_prompts(self, manager, mock_store):
        mock_store.get_all_prompts.return_value = {
            "worker": "You are a worker.",
            "planner": "You are a planner.",
        }
        exp_id = uuid.uuid4()
        await manager.capture(exp_id)

        # Verify the snapshot data passed to create_snapshot includes prompts
        call_args = mock_store.create_snapshot.call_args
        snapshot_data = call_args[0][1]  # (experiment_id, data)
        assert snapshot_data["prompts"] == {
            "worker": "You are a worker.",
            "planner": "You are a planner.",
        }

    async def test_collects_tool_configs(self, manager, mock_store):
        mock_store.get_all_tool_configs.return_value = {
            "shell": {"timeout": 30},
            "http": {"timeout": 10},
        }
        exp_id = uuid.uuid4()
        await manager.capture(exp_id)

        call_args = mock_store.create_snapshot.call_args
        snapshot_data = call_args[0][1]
        assert snapshot_data["tool_configs"] == {
            "shell": {"timeout": 30},
            "http": {"timeout": 10},
        }

    async def test_collects_metric_baselines(self, manager, mock_store, mock_metrics):
        baseline_obj = AsyncMock()
        baseline_obj.mean = 0.85
        mock_metrics.get_baseline.side_effect = [baseline_obj, None]

        exp_id = uuid.uuid4()
        await manager.capture(exp_id)

        call_args = mock_store.create_snapshot.call_args
        snapshot_data = call_args[0][1]
        assert "metrics_baseline" in snapshot_data
        assert snapshot_data["metrics_baseline"]["audit_score"] == 0.85
        # audit_duration_seconds had None baseline, should not appear or be 0
        assert "audit_duration_seconds" not in snapshot_data["metrics_baseline"]

    async def test_passes_experiment_id_to_store(self, manager, mock_store):
        exp_id = uuid.uuid4()
        await manager.capture(exp_id)
        mock_store.create_snapshot.assert_called_once()
        assert mock_store.create_snapshot.call_args[0][0] == exp_id

    async def test_includes_empty_context_rules(self, manager, mock_store):
        exp_id = uuid.uuid4()
        await manager.capture(exp_id)
        call_args = mock_store.create_snapshot.call_args
        snapshot_data = call_args[0][1]
        assert "context_rules" in snapshot_data
        assert snapshot_data["context_rules"] == []


# ── Restore ───────────────────────────────────────────────────────────────


class TestRestore:
    async def test_restores_prompts(self, manager, mock_store):
        snapshot_data = {
            "prompts": {"worker": "Prompt A", "planner": "Prompt B"},
            "tool_configs": {},
            "context_rules": [],
            "metrics_baseline": {},
        }
        mock_store.get_snapshot.return_value = {
            "id": uuid.uuid4(),
            "experiment_id": uuid.uuid4(),
            "snapshot_data": json.dumps(snapshot_data),
            "metrics_baseline": json.dumps({}),
        }
        exp_id = uuid.uuid4()
        await manager.restore(exp_id)

        assert mock_store.set_prompt.call_count == 2
        # Verify each prompt was restored
        call_args_list = [c[0] for c in mock_store.set_prompt.call_args_list]
        agent_types = {args[0] for args in call_args_list}
        assert agent_types == {"worker", "planner"}

    async def test_restores_tool_configs(self, manager, mock_store):
        snapshot_data = {
            "prompts": {},
            "tool_configs": {
                "shell": {"timeout": 30},
                "http": {"timeout": 10},
            },
            "context_rules": [],
            "metrics_baseline": {},
        }
        mock_store.get_snapshot.return_value = {
            "id": uuid.uuid4(),
            "experiment_id": uuid.uuid4(),
            "snapshot_data": json.dumps(snapshot_data),
            "metrics_baseline": json.dumps({}),
        }
        exp_id = uuid.uuid4()
        await manager.restore(exp_id)

        assert mock_store.set_tool_config.call_count == 2
        call_args_list = [c[0] for c in mock_store.set_tool_config.call_args_list]
        tool_ids = {args[0] for args in call_args_list}
        assert tool_ids == {"shell", "http"}

    async def test_raises_on_missing_snapshot(self, manager, mock_store):
        mock_store.get_snapshot.return_value = None
        exp_id = uuid.uuid4()
        with pytest.raises(ValueError, match="No snapshot found"):
            await manager.restore(exp_id)

    async def test_handles_snapshot_data_as_dict(self, manager, mock_store):
        """When snapshot_data is already a dict (not a JSON string)."""
        snapshot_data = {
            "prompts": {"worker": "Restored prompt"},
            "tool_configs": {"shell": {"timeout": 60}},
            "context_rules": [],
            "metrics_baseline": {},
        }
        mock_store.get_snapshot.return_value = {
            "id": uuid.uuid4(),
            "experiment_id": uuid.uuid4(),
            "snapshot_data": snapshot_data,  # Already a dict
            "metrics_baseline": {},
        }
        exp_id = uuid.uuid4()
        await manager.restore(exp_id)

        mock_store.set_prompt.assert_called_once_with("worker", "Restored prompt")
        mock_store.set_tool_config.assert_called_once_with("shell", {"timeout": 60})

    async def test_restore_with_empty_snapshot(self, manager, mock_store):
        """Restore from a snapshot that has no prompts or configs."""
        snapshot_data = {
            "prompts": {},
            "tool_configs": {},
            "context_rules": [],
            "metrics_baseline": {},
        }
        mock_store.get_snapshot.return_value = {
            "id": uuid.uuid4(),
            "experiment_id": uuid.uuid4(),
            "snapshot_data": json.dumps(snapshot_data),
            "metrics_baseline": json.dumps({}),
        }
        exp_id = uuid.uuid4()
        await manager.restore(exp_id)

        mock_store.set_prompt.assert_not_called()
        mock_store.set_tool_config.assert_not_called()

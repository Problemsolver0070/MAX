"""Tests for Orchestrator audit integration and fix loop."""

import uuid
from unittest.mock import AsyncMock

import pytest

from max.agents.base import AgentConfig
from max.command.models import ExecutionPlan, PlannedSubtask, SubtaskResult
from max.command.orchestrator import OrchestratorAgent
from max.config import Settings
from max.llm.models import ModelType


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_orchestrator(monkeypatch):
    settings = _make_settings(monkeypatch)
    llm = AsyncMock()
    bus = AsyncMock()
    bus.subscribe = AsyncMock()
    bus.unsubscribe = AsyncMock()
    bus.publish = AsyncMock()
    db = AsyncMock()
    warm = AsyncMock()
    task_store = AsyncMock()
    task_store.get_task = AsyncMock(
        return_value={
            "id": uuid.uuid4(),
            "goal_anchor": "Test goal",
            "quality_criteria": {},
            "status": "in_progress",
        }
    )
    task_store.update_task_status = AsyncMock()
    task_store.update_subtask_status = AsyncMock()
    task_store.update_subtask_result = AsyncMock()
    task_store.create_result = AsyncMock(return_value=uuid.uuid4())
    runner = AsyncMock()

    config = AgentConfig(name="orchestrator", system_prompt="", model=ModelType.OPUS)
    orch = OrchestratorAgent(
        config=config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm,
        settings=settings,
        task_store=task_store,
        runner=runner,
    )
    return orch, bus, task_store, runner


class TestAuditRequestPublished:
    @pytest.mark.asyncio
    async def test_publishes_audit_request_on_success(self, monkeypatch):
        orch, bus, task_store, runner = _make_orchestrator(monkeypatch)

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        task_store.get_subtasks = AsyncMock(
            return_value=[
                {
                    "id": subtask_id,
                    "description": "Write code",
                    "phase_number": 1,
                    "quality_criteria": {},
                    "status": "pending",
                }
            ]
        )
        runner.run = AsyncMock(
            return_value=SubtaskResult(
                subtask_id=subtask_id,
                task_id=task_id,
                success=True,
                content="Hello world",
                confidence=0.9,
            )
        )

        plan = ExecutionPlan(
            task_id=task_id,
            goal_anchor="Test",
            subtasks=[PlannedSubtask(description="Write code", phase_number=1)],
            total_phases=1,
            reasoning="test",
        )
        await orch.on_execute("tasks.execute", plan.model_dump(mode="json"))

        # Should publish audit.request instead of tasks.complete
        channels = [c[0][0] for c in bus.publish.call_args_list]
        assert "audit.request" in channels
        assert "tasks.complete" not in channels


class TestAuditCompleteSuccess:
    @pytest.mark.asyncio
    async def test_publishes_tasks_complete_on_audit_pass(self, monkeypatch):
        orch, bus, task_store, runner = _make_orchestrator(monkeypatch)

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        # Pre-populate pending audit
        orch._pending_audits[task_id] = {
            "prior_results": [
                SubtaskResult(
                    subtask_id=subtask_id,
                    task_id=task_id,
                    success=True,
                    content="Hello world",
                    confidence=0.9,
                ),
            ],
            "db_subtasks": [{"id": subtask_id, "description": "test", "quality_criteria": {}}],
            "fix_attempt": 0,
            "goal_anchor": "Test",
            "quality_criteria": {},
        }

        audit_response = {
            "task_id": str(task_id),
            "success": True,
            "verdicts": [
                {
                    "subtask_id": str(subtask_id),
                    "verdict": "pass",
                    "score": 0.85,
                    "goal_alignment": 0.9,
                    "issues": [],
                }
            ],
            "overall_score": 0.85,
            "fix_required": [],
        }
        await orch.on_audit_complete("audit.complete", audit_response)

        channels = [c[0][0] for c in bus.publish.call_args_list]
        assert "tasks.complete" in channels
        complete_payload = next(
            c[0][1] for c in bus.publish.call_args_list if c[0][0] == "tasks.complete"
        )
        assert complete_payload["success"] is True


class TestFixLoop:
    @pytest.mark.asyncio
    async def test_reexecutes_failed_subtasks(self, monkeypatch):
        orch, bus, task_store, runner = _make_orchestrator(monkeypatch)

        task_id = uuid.uuid4()
        failed_id = uuid.uuid4()
        pass_id = uuid.uuid4()

        orch._pending_audits[task_id] = {
            "prior_results": [
                SubtaskResult(
                    subtask_id=pass_id,
                    task_id=task_id,
                    success=True,
                    content="good",
                    confidence=0.9,
                ),
                SubtaskResult(
                    subtask_id=failed_id,
                    task_id=task_id,
                    success=True,
                    content="bad",
                    confidence=0.8,
                ),
            ],
            "db_subtasks": [
                {
                    "id": pass_id,
                    "description": "passed task",
                    "quality_criteria": {},
                    "phase_number": 1,
                },
                {
                    "id": failed_id,
                    "description": "failed task",
                    "quality_criteria": {},
                    "phase_number": 1,
                },
            ],
            "fix_attempt": 0,
            "goal_anchor": "Test",
            "quality_criteria": {},
        }

        runner.run = AsyncMock(
            return_value=SubtaskResult(
                subtask_id=failed_id,
                task_id=task_id,
                success=True,
                content="fixed output",
                confidence=0.9,
            )
        )

        audit_response = {
            "task_id": str(task_id),
            "success": False,
            "verdicts": [
                {
                    "subtask_id": str(pass_id),
                    "verdict": "pass",
                    "score": 0.9,
                    "goal_alignment": 0.9,
                    "issues": [],
                },
                {
                    "subtask_id": str(failed_id),
                    "verdict": "fail",
                    "score": 0.3,
                    "goal_alignment": 0.4,
                    "issues": [{"category": "q", "description": "bad"}],
                },
            ],
            "overall_score": 0.6,
            "fix_required": [
                {
                    "subtask_id": str(failed_id),
                    "instructions": "Fix the issues",
                    "original_content": "bad",
                    "issues": [{"category": "q", "description": "bad"}],
                }
            ],
        }
        await orch.on_audit_complete("audit.complete", audit_response)

        # Should re-execute only the failed subtask
        runner.run.assert_called_once()
        # Should publish audit.request again (for re-audit)
        audit_req_calls = [c for c in bus.publish.call_args_list if c[0][0] == "audit.request"]
        assert len(audit_req_calls) == 1

    @pytest.mark.asyncio
    async def test_fails_after_max_fix_attempts(self, monkeypatch):
        orch, bus, task_store, runner = _make_orchestrator(monkeypatch)

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        orch._pending_audits[task_id] = {
            "prior_results": [
                SubtaskResult(
                    subtask_id=subtask_id,
                    task_id=task_id,
                    success=True,
                    content="bad",
                    confidence=0.8,
                ),
            ],
            "db_subtasks": [
                {
                    "id": subtask_id,
                    "description": "test",
                    "quality_criteria": {},
                    "phase_number": 1,
                },
            ],
            "fix_attempt": 2,  # Already at max
            "goal_anchor": "Test",
            "quality_criteria": {},
        }

        audit_response = {
            "task_id": str(task_id),
            "success": False,
            "verdicts": [
                {
                    "subtask_id": str(subtask_id),
                    "verdict": "fail",
                    "score": 0.3,
                    "goal_alignment": 0.4,
                    "issues": [{"category": "q", "description": "bad"}],
                },
            ],
            "overall_score": 0.3,
            "fix_required": [
                {
                    "subtask_id": str(subtask_id),
                    "instructions": "Fix it",
                    "original_content": "bad",
                    "issues": [],
                },
            ],
        }
        await orch.on_audit_complete("audit.complete", audit_response)

        # Should publish tasks.complete with failure (not re-execute)
        channels = [c[0][0] for c in bus.publish.call_args_list]
        assert "tasks.complete" in channels
        complete = next(c[0][1] for c in bus.publish.call_args_list if c[0][0] == "tasks.complete")
        assert complete["success"] is False


class TestAuditSubscription:
    @pytest.mark.asyncio
    async def test_start_subscribes_to_audit_complete(self, monkeypatch):
        orch, bus, *_ = _make_orchestrator(monkeypatch)
        await orch.start()
        channels = [c[0][0] for c in bus.subscribe.call_args_list]
        assert "audit.complete" in channels

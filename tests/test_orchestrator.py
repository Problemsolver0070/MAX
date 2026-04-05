import uuid
from unittest.mock import AsyncMock

import pytest

from max.agents.base import AgentConfig
from max.command.models import SubtaskResult
from max.command.orchestrator import OrchestratorAgent
from max.config import Settings
from max.llm.models import ModelType


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_orchestrator(bus, db, warm, settings, runner=None, *, task_id=None):
    config = AgentConfig(name="orchestrator", system_prompt="", model=ModelType.OPUS)
    llm = AsyncMock()
    task_store = AsyncMock()
    # Provide a realistic get_task return so the audit path works.
    task_store.get_task = AsyncMock(
        return_value={
            "id": task_id or uuid.uuid4(),
            "goal_anchor": "Test goal",
            "quality_criteria": {},
            "status": "in_progress",
        }
    )
    task_store.update_task_status = AsyncMock()
    if runner is None:
        runner = AsyncMock()
    return OrchestratorAgent(
        config=config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm,
        settings=settings,
        task_store=task_store,
        runner=runner,
    )


class TestOrchestratorExecution:
    @pytest.mark.asyncio
    async def test_single_phase_execution(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        subtask_id = uuid.uuid4()
        task_id = uuid.uuid4()

        runner = AsyncMock()
        runner.run = AsyncMock(
            return_value=SubtaskResult(
                subtask_id=subtask_id,
                task_id=task_id,
                success=True,
                content="Done",
                confidence=0.9,
            )
        )

        orch = _make_orchestrator(bus, db, warm, settings, runner)
        orch._task_store.get_subtasks = AsyncMock(
            return_value=[
                {
                    "id": subtask_id,
                    "description": "Do work",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "status": "pending",
                },
            ]
        )
        orch._task_store.update_subtask_result = AsyncMock()
        orch._task_store.update_subtask_status = AsyncMock()
        orch._task_store.create_result = AsyncMock(return_value=uuid.uuid4())

        plan_data = {
            "task_id": str(task_id),
            "goal_anchor": "Test task",
            "subtasks": [
                {
                    "description": "Do work",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "estimated_complexity": "moderate",
                },
            ],
            "total_phases": 1,
            "reasoning": "Simple task",
            "created_at": "2026-04-05T00:00:00Z",
        }
        await orch.on_execute("tasks.execute", plan_data)

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        # After audit integration, successful execution publishes audit.request
        # instead of tasks.complete (tasks.complete is deferred to on_audit_complete).
        assert "audit.request" in channels
        assert "tasks.complete" not in channels

    @pytest.mark.asyncio
    async def test_multi_phase_execution(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        s1_id, s2_id, s3_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        runner = AsyncMock()
        runner.run = AsyncMock(
            side_effect=[
                SubtaskResult(
                    subtask_id=s1_id,
                    task_id=task_id,
                    success=True,
                    content="A",
                    confidence=0.9,
                ),
                SubtaskResult(
                    subtask_id=s2_id,
                    task_id=task_id,
                    success=True,
                    content="B",
                    confidence=0.8,
                ),
                SubtaskResult(
                    subtask_id=s3_id,
                    task_id=task_id,
                    success=True,
                    content="C",
                    confidence=0.95,
                ),
            ]
        )

        orch = _make_orchestrator(bus, db, warm, settings, runner)
        orch._task_store.get_subtasks = AsyncMock(
            return_value=[
                {
                    "id": s1_id,
                    "description": "Step A",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "status": "pending",
                },
                {
                    "id": s2_id,
                    "description": "Step B",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "status": "pending",
                },
                {
                    "id": s3_id,
                    "description": "Step C",
                    "phase_number": 2,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "status": "pending",
                },
            ]
        )
        orch._task_store.update_subtask_result = AsyncMock()
        orch._task_store.update_subtask_status = AsyncMock()
        orch._task_store.create_result = AsyncMock(return_value=uuid.uuid4())

        plan_data = {
            "task_id": str(task_id),
            "goal_anchor": "Multi-phase task",
            "subtasks": [
                {
                    "description": "Step A",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "estimated_complexity": "low",
                },
                {
                    "description": "Step B",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "estimated_complexity": "low",
                },
                {
                    "description": "Step C",
                    "phase_number": 2,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "estimated_complexity": "moderate",
                },
            ],
            "total_phases": 2,
            "reasoning": "Two phases",
            "created_at": "2026-04-05T00:00:00Z",
        }
        await orch.on_execute("tasks.execute", plan_data)

        assert runner.run.call_count == 3

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        # After audit integration, successful execution publishes audit.request.
        assert "audit.request" in channels

    @pytest.mark.asyncio
    async def test_worker_failure_with_retry(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        s_id = uuid.uuid4()

        runner = AsyncMock()
        runner.run = AsyncMock(
            side_effect=[
                SubtaskResult(
                    subtask_id=s_id,
                    task_id=task_id,
                    success=False,
                    error="Temp error",
                ),
                SubtaskResult(
                    subtask_id=s_id,
                    task_id=task_id,
                    success=False,
                    error="Temp error",
                ),
                SubtaskResult(
                    subtask_id=s_id,
                    task_id=task_id,
                    success=True,
                    content="OK",
                    confidence=0.7,
                ),
            ]
        )

        orch = _make_orchestrator(bus, db, warm, settings, runner)
        orch._task_store.get_subtasks = AsyncMock(
            return_value=[
                {
                    "id": s_id,
                    "description": "Flaky task",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "status": "pending",
                },
            ]
        )
        orch._task_store.update_subtask_result = AsyncMock()
        orch._task_store.update_subtask_status = AsyncMock()
        orch._task_store.create_result = AsyncMock(return_value=uuid.uuid4())

        plan_data = {
            "task_id": str(task_id),
            "goal_anchor": "Flaky task",
            "subtasks": [
                {
                    "description": "Flaky task",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "estimated_complexity": "moderate",
                },
            ],
            "total_phases": 1,
            "reasoning": "Single step",
            "created_at": "2026-04-05T00:00:00Z",
        }
        await orch.on_execute("tasks.execute", plan_data)

        # 1 initial + 2 retries = 3 total calls
        assert runner.run.call_count == 3

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        # After audit integration, successful execution publishes audit.request.
        assert "audit.request" in channels

    @pytest.mark.asyncio
    async def test_worker_exhausts_retries(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        s_id = uuid.uuid4()

        runner = AsyncMock()
        runner.run = AsyncMock(
            return_value=SubtaskResult(
                subtask_id=s_id,
                task_id=task_id,
                success=False,
                error="Persistent error",
            )
        )

        orch = _make_orchestrator(bus, db, warm, settings, runner)
        orch._task_store.get_subtasks = AsyncMock(
            return_value=[
                {
                    "id": s_id,
                    "description": "Doomed task",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "status": "pending",
                },
            ]
        )
        orch._task_store.update_subtask_result = AsyncMock()
        orch._task_store.update_subtask_status = AsyncMock()

        plan_data = {
            "task_id": str(task_id),
            "goal_anchor": "Doomed task",
            "subtasks": [
                {
                    "description": "Doomed task",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "estimated_complexity": "moderate",
                },
            ],
            "total_phases": 1,
            "reasoning": "Will fail",
            "created_at": "2026-04-05T00:00:00Z",
        }
        await orch.on_execute("tasks.execute", plan_data)

        # 1 initial + 2 retries = 3 total calls
        assert runner.run.call_count == 3

        calls = bus.publish.call_args_list
        complete = next(c for c in calls if c[0][0] == "tasks.complete")
        assert complete[0][1]["success"] is False

    @pytest.mark.asyncio
    async def test_phase_two_not_run_when_phase_one_fails(self, monkeypatch):
        """If a subtask in phase 1 fails all retries, phase 2 should not execute."""
        settings = _make_settings(monkeypatch)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        s1_id, s2_id = uuid.uuid4(), uuid.uuid4()

        runner = AsyncMock()
        runner.run = AsyncMock(
            return_value=SubtaskResult(
                subtask_id=s1_id,
                task_id=task_id,
                success=False,
                error="Phase 1 failed",
            )
        )

        orch = _make_orchestrator(bus, db, warm, settings, runner)
        orch._task_store.get_subtasks = AsyncMock(
            return_value=[
                {
                    "id": s1_id,
                    "description": "P1 work",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "status": "pending",
                },
                {
                    "id": s2_id,
                    "description": "P2 work",
                    "phase_number": 2,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "status": "pending",
                },
            ]
        )
        orch._task_store.update_subtask_result = AsyncMock()
        orch._task_store.update_subtask_status = AsyncMock()

        plan_data = {
            "task_id": str(task_id),
            "goal_anchor": "Two-phase failing",
            "subtasks": [
                {
                    "description": "P1 work",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "estimated_complexity": "moderate",
                },
                {
                    "description": "P2 work",
                    "phase_number": 2,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "estimated_complexity": "moderate",
                },
            ],
            "total_phases": 2,
            "reasoning": "Two phases",
            "created_at": "2026-04-05T00:00:00Z",
        }
        await orch.on_execute("tasks.execute", plan_data)

        # Only phase 1 subtask attempted (1 + 2 retries = 3), phase 2 never runs
        assert runner.run.call_count == 3

        calls = bus.publish.call_args_list
        complete = next(c for c in calls if c[0][0] == "tasks.complete")
        assert complete[0][1]["success"] is False

    @pytest.mark.asyncio
    async def test_progress_events_published(self, monkeypatch):
        """After each phase completes, a progress event should be published."""
        settings = _make_settings(monkeypatch)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        s1_id = uuid.uuid4()

        runner = AsyncMock()
        runner.run = AsyncMock(
            return_value=SubtaskResult(
                subtask_id=s1_id,
                task_id=task_id,
                success=True,
                content="Done",
                confidence=0.9,
            )
        )

        orch = _make_orchestrator(bus, db, warm, settings, runner)
        orch._task_store.get_subtasks = AsyncMock(
            return_value=[
                {
                    "id": s1_id,
                    "description": "Work",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "status": "pending",
                },
            ]
        )
        orch._task_store.update_subtask_result = AsyncMock()
        orch._task_store.update_subtask_status = AsyncMock()
        orch._task_store.create_result = AsyncMock(return_value=uuid.uuid4())

        plan_data = {
            "task_id": str(task_id),
            "goal_anchor": "Progress test",
            "subtasks": [
                {
                    "description": "Work",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "estimated_complexity": "low",
                },
            ],
            "total_phases": 1,
            "reasoning": "One step",
            "created_at": "2026-04-05T00:00:00Z",
        }
        await orch.on_execute("tasks.execute", plan_data)

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "status_updates.new" in channels


class TestOrchestratorCancellation:
    @pytest.mark.asyncio
    async def test_cancel_task(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        orch = _make_orchestrator(bus, db, warm, settings)
        orch._task_store.get_subtasks = AsyncMock(
            return_value=[
                {"id": uuid.uuid4(), "status": "in_progress"},
            ]
        )
        orch._task_store.update_subtask_status = AsyncMock()

        await orch.on_cancel("tasks.cancel", {"task_id": str(task_id)})
        assert task_id in orch._cancelled_tasks

    @pytest.mark.asyncio
    async def test_cancel_marks_subtasks_as_failed(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        st_id = uuid.uuid4()
        orch = _make_orchestrator(bus, db, warm, settings)
        orch._task_store.get_subtasks = AsyncMock(
            return_value=[
                {"id": st_id, "status": "in_progress"},
                {"id": uuid.uuid4(), "status": "completed"},
            ]
        )
        orch._task_store.update_subtask_status = AsyncMock()

        await orch.on_cancel("tasks.cancel", {"task_id": str(task_id)})

        # Only the in_progress subtask should be marked failed
        orch._task_store.update_subtask_status.assert_called_once()


class TestOrchestratorLifecycle:
    @pytest.mark.asyncio
    async def test_start_subscribes(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        orch = _make_orchestrator(bus, db, warm, settings)
        await orch.start()

        channels = [c[0][0] for c in bus.subscribe.call_args_list]
        assert "tasks.execute" in channels
        assert "tasks.cancel" in channels
        assert "tasks.context_update" in channels

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        orch = _make_orchestrator(bus, db, warm, settings)
        await orch.start()
        await orch.stop()

        channels = [c[0][0] for c in bus.unsubscribe.call_args_list]
        assert "tasks.execute" in channels
        assert "tasks.cancel" in channels


class TestOrchestratorResultAssembly:
    @pytest.mark.asyncio
    async def test_combined_result_via_audit(self, monkeypatch):
        """Verify that on_audit_complete assembles combined result from subtask content."""
        settings = _make_settings(monkeypatch)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        s1_id, s2_id = uuid.uuid4(), uuid.uuid4()

        orch = _make_orchestrator(bus, db, warm, settings)
        orch._task_store.create_result = AsyncMock(return_value=uuid.uuid4())

        # Pre-populate pending audit (simulates on_execute having run)
        orch._pending_audits[task_id] = {
            "prior_results": [
                SubtaskResult(
                    subtask_id=s1_id,
                    task_id=task_id,
                    success=True,
                    content="First result",
                    confidence=0.8,
                ),
                SubtaskResult(
                    subtask_id=s2_id,
                    task_id=task_id,
                    success=True,
                    content="Second result",
                    confidence=0.9,
                ),
            ],
            "db_subtasks": [
                {"id": s1_id, "description": "Step 1", "quality_criteria": {}},
                {"id": s2_id, "description": "Step 2", "quality_criteria": {}},
            ],
            "fix_attempt": 0,
            "goal_anchor": "Assembly test",
            "quality_criteria": {},
        }

        audit_response = {
            "task_id": str(task_id),
            "success": True,
            "verdicts": [
                {
                    "subtask_id": str(s1_id),
                    "verdict": "pass",
                    "score": 0.9,
                    "goal_alignment": 0.9,
                    "issues": [],
                },
                {
                    "subtask_id": str(s2_id),
                    "verdict": "pass",
                    "score": 0.85,
                    "goal_alignment": 0.9,
                    "issues": [],
                },
            ],
            "overall_score": 0.875,
            "fix_required": [],
        }
        await orch.on_audit_complete("audit.complete", audit_response)

        calls = bus.publish.call_args_list
        complete = next(c for c in calls if c[0][0] == "tasks.complete")
        result_content = complete[0][1]["result_content"]
        assert "First result" in result_content
        assert "Second result" in result_content

        # Verify confidence is averaged
        assert complete[0][1]["confidence"] == pytest.approx(0.85, abs=0.01)

    @pytest.mark.asyncio
    async def test_create_result_called_on_audit_pass(self, monkeypatch):
        """Verify that task_store.create_result is called when audit passes."""
        settings = _make_settings(monkeypatch)
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        s_id = uuid.uuid4()

        orch = _make_orchestrator(bus, db, warm, settings)
        orch._task_store.create_result = AsyncMock(return_value=uuid.uuid4())

        # Pre-populate pending audit
        orch._pending_audits[task_id] = {
            "prior_results": [
                SubtaskResult(
                    subtask_id=s_id,
                    task_id=task_id,
                    success=True,
                    content="Result",
                    confidence=0.9,
                ),
            ],
            "db_subtasks": [
                {"id": s_id, "description": "Work", "quality_criteria": {}},
            ],
            "fix_attempt": 0,
            "goal_anchor": "Store result",
            "quality_criteria": {},
        }

        audit_response = {
            "task_id": str(task_id),
            "success": True,
            "verdicts": [
                {
                    "subtask_id": str(s_id),
                    "verdict": "pass",
                    "score": 0.9,
                    "goal_alignment": 0.9,
                    "issues": [],
                },
            ],
            "overall_score": 0.9,
            "fix_required": [],
        }
        await orch.on_audit_complete("audit.complete", audit_response)

        orch._task_store.create_result.assert_called_once()
        call_kwargs = orch._task_store.create_result.call_args
        assert call_kwargs[1]["task_id"] == task_id
        assert call_kwargs[1]["confidence"] == pytest.approx(0.9)

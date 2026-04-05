import uuid

import pytest

from max.command.models import (
    CoordinatorAction,
    CoordinatorActionType,
    ExecutionPlan,
    PlannedSubtask,
    SubtaskResult,
    WorkerConfig,
)
from max.models.messages import Priority


class TestCoordinatorActionType:
    def test_enum_values(self):
        assert CoordinatorActionType.CREATE_TASK == "create_task"
        assert CoordinatorActionType.QUERY_STATUS == "query_status"
        assert CoordinatorActionType.CANCEL_TASK == "cancel_task"
        assert CoordinatorActionType.PROVIDE_CONTEXT == "provide_context"
        assert CoordinatorActionType.CLARIFICATION_RESPONSE == "clarification_response"


class TestCoordinatorAction:
    def test_create_task_action(self):
        action = CoordinatorAction(
            action=CoordinatorActionType.CREATE_TASK,
            goal_anchor="Deploy the app",
            priority=Priority.HIGH,
            reasoning="User wants deployment",
        )
        assert action.action == CoordinatorActionType.CREATE_TASK
        assert action.goal_anchor == "Deploy the app"
        assert action.priority == Priority.HIGH
        assert action.task_id is None

    def test_cancel_task_action(self):
        tid = uuid.uuid4()
        action = CoordinatorAction(
            action=CoordinatorActionType.CANCEL_TASK,
            task_id=tid,
            reasoning="User said cancel",
        )
        assert action.task_id == tid

    def test_defaults(self):
        action = CoordinatorAction(action=CoordinatorActionType.QUERY_STATUS)
        assert action.goal_anchor == ""
        assert action.priority == Priority.NORMAL
        assert action.context_text == ""
        assert action.clarification_answer == ""
        assert action.reasoning == ""
        assert action.quality_criteria == {}

    def test_serialization_roundtrip(self):
        action = CoordinatorAction(
            action=CoordinatorActionType.CREATE_TASK,
            goal_anchor="Test",
        )
        data = action.model_dump(mode="json")
        restored = CoordinatorAction.model_validate(data)
        assert restored.action == action.action
        assert restored.goal_anchor == action.goal_anchor


class TestPlannedSubtask:
    def test_defaults(self):
        ps = PlannedSubtask(description="Do thing", phase_number=1)
        assert ps.description == "Do thing"
        assert ps.phase_number == 1
        assert ps.tool_categories == []
        assert ps.quality_criteria == {}
        assert ps.estimated_complexity == "moderate"

    def test_full_construction(self):
        ps = PlannedSubtask(
            description="Run tests",
            phase_number=2,
            tool_categories=["code"],
            quality_criteria={"coverage": ">80%"},
            estimated_complexity="high",
        )
        assert ps.tool_categories == ["code"]
        assert ps.estimated_complexity == "high"


class TestExecutionPlan:
    def test_construction(self):
        tid = uuid.uuid4()
        plan = ExecutionPlan(
            task_id=tid,
            goal_anchor="Deploy app",
            subtasks=[
                PlannedSubtask(description="Check build", phase_number=1),
                PlannedSubtask(description="Deploy", phase_number=2),
            ],
            total_phases=2,
            reasoning="Sequential deployment",
        )
        assert plan.task_id == tid
        assert len(plan.subtasks) == 2
        assert plan.total_phases == 2
        assert plan.created_at is not None

    def test_serialization_roundtrip(self):
        plan = ExecutionPlan(
            task_id=uuid.uuid4(),
            goal_anchor="Test",
            subtasks=[PlannedSubtask(description="Step 1", phase_number=1)],
            total_phases=1,
            reasoning="Simple",
        )
        data = plan.model_dump(mode="json")
        restored = ExecutionPlan.model_validate(data)
        assert restored.task_id == plan.task_id
        assert len(restored.subtasks) == 1


class TestWorkerConfig:
    def test_construction(self):
        wc = WorkerConfig(
            subtask_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            system_prompt="You are a worker.",
        )
        assert wc.tool_ids == []
        assert wc.context_package == {}
        assert wc.quality_criteria == {}
        assert wc.max_turns == 10

    def test_full_construction(self):
        wc = WorkerConfig(
            subtask_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            system_prompt="Do work",
            tool_ids=["search", "code_exec"],
            context_package={"anchors": []},
            quality_criteria={"accuracy": "high"},
            max_turns=5,
        )
        assert len(wc.tool_ids) == 2
        assert wc.max_turns == 5


class TestSubtaskResult:
    def test_success_result(self):
        sr = SubtaskResult(
            subtask_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            success=True,
            content="Task completed",
            confidence=0.95,
            reasoning="Straightforward task",
        )
        assert sr.success is True
        assert sr.error is None

    def test_failure_result(self):
        sr = SubtaskResult(
            subtask_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            success=False,
            error="Worker timed out",
        )
        assert sr.success is False
        assert sr.content == ""
        assert sr.confidence == 0.0

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            SubtaskResult(
                subtask_id=uuid.uuid4(),
                task_id=uuid.uuid4(),
                success=True,
                confidence=1.5,
            )

    def test_serialization_roundtrip(self):
        sr = SubtaskResult(
            subtask_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            success=True,
            content="Done",
            confidence=0.8,
        )
        data = sr.model_dump(mode="json")
        restored = SubtaskResult.model_validate(data)
        assert restored.subtask_id == sr.subtask_id
        assert restored.confidence == sr.confidence

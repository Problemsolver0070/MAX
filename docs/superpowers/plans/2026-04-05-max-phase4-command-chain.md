# Phase 4: Command Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the three-agent command chain (Coordinator, Planner, Orchestrator) that closes the intent-to-result loop — receiving parsed intents from Phase 3's Communicator and producing results the user can see.

**Architecture:** Coordinator (classify intents, route, manage state) -> Planner (decompose tasks into phased subtasks) -> Orchestrator (spawn WorkerAgents, collect results). All agents extend BaseAgent, communicate exclusively via Redis pub/sub bus, persist to PostgreSQL. AgentRunner abstraction enables future subprocess isolation.

**Tech Stack:** Python 3.12+, asyncio, pydantic v2, asyncpg (PostgreSQL), redis.asyncio, anthropic SDK, pytest-asyncio

---

## File Structure

```
src/max/command/
    __init__.py               # Package exports (8 public symbols)
    models.py                 # CoordinatorActionType, CoordinatorAction, PlannedSubtask,
                              #   ExecutionPlan, WorkerConfig, SubtaskResult
    task_store.py             # TaskStore: async CRUD for tasks/subtasks over PostgreSQL
    coordinator.py            # CoordinatorAgent: intent classification, routing, state mgmt
    planner.py                # PlannerAgent: task decomposition, clarification, exec plans
    orchestrator.py           # OrchestratorAgent: phase execution, worker lifecycle, results
    worker.py                 # WorkerAgent: generic ephemeral subtask executor
    runner.py                 # AgentRunner ABC + InProcessRunner

src/max/db/migrations/
    004_command_chain.sql     # ALTER subtasks + tasks for Phase 4 columns

tests/
    test_command_models.py    # Model validation tests
    test_task_store.py        # TaskStore CRUD against real PostgreSQL
    test_coordinator.py       # Coordinator routing tests (mocked LLM)
    test_planner.py           # Planner decomposition tests (mocked LLM)
    test_orchestrator.py      # Orchestrator phase execution tests (mocked runner)
    test_worker.py            # Worker execution tests (mocked LLM)
    test_runner.py            # InProcessRunner tests
    test_command_integration.py  # End-to-end intent → result pipeline
```

---

### Task 1: Configuration and Database Migration

**Files:**
- Modify: `src/max/config.py:61` (add Phase 4 settings after webhook block)
- Create: `src/max/db/migrations/004_command_chain.sql`
- Modify: `src/max/db/schema.sql` (append Phase 4 alterations)
- Modify: `tests/test_config.py` (add Phase 4 defaults test)
- Modify: `tests/test_postgres.py` (add Phase 4 column verification test, update fixture)

- [ ] **Step 1: Write the failing config test**

Add to `tests/test_config.py`:

```python
def test_command_chain_settings_defaults(settings):
    assert settings.coordinator_model == "claude-opus-4-6"
    assert settings.planner_model == "claude-opus-4-6"
    assert settings.orchestrator_model == "claude-opus-4-6"
    assert settings.worker_model == "claude-opus-4-6"
    assert settings.coordinator_max_active_tasks == 5
    assert settings.planner_max_subtasks == 10
    assert settings.worker_max_retries == 2
    assert settings.worker_timeout_seconds == 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_config.py::test_command_chain_settings_defaults -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'coordinator_model'`

- [ ] **Step 3: Add Phase 4 settings to config.py**

Add after line 61 (after `comm_webhook_secret`) in `src/max/config.py`:

```python
    # Command chain
    coordinator_model: str = "claude-opus-4-6"
    planner_model: str = "claude-opus-4-6"
    orchestrator_model: str = "claude-opus-4-6"
    worker_model: str = "claude-opus-4-6"
    coordinator_max_active_tasks: int = 5
    planner_max_subtasks: int = 10
    worker_max_retries: int = 2
    worker_timeout_seconds: int = 300
```

- [ ] **Step 4: Run config test to verify it passes**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_config.py::test_command_chain_settings_defaults -v`
Expected: PASS

- [ ] **Step 5: Write the failing DB column test**

Add to `tests/test_postgres.py`:

```python
@pytest.mark.asyncio
async def test_subtasks_has_phase4_columns(db):
    """Verify subtasks table has Phase 4 columns."""
    cols = await db.fetchall(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'subtasks'"
    )
    col_names = {row["column_name"] for row in cols}
    expected = {
        "phase_number",
        "tool_categories",
        "worker_agent_id",
        "retry_count",
        "quality_criteria",
        "estimated_complexity",
    }
    assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"


@pytest.mark.asyncio
async def test_tasks_has_priority_column(db):
    """Verify tasks table has Phase 4 priority column."""
    cols = await db.fetchall(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'tasks'"
    )
    col_names = {row["column_name"] for row in cols}
    assert "priority" in col_names
```

Also update the `db` fixture in `tests/test_postgres.py` to add the new DROP/DELETE statements. In the fixture's DROP block, no changes needed (subtasks and tasks already dropped). But the new columns are added via ALTER, which happens in `init_schema()`. Ensure the fixture drops and recreates cleanly.

- [ ] **Step 6: Create migration file**

Create `src/max/db/migrations/004_command_chain.sql`:

```sql
-- ═════════════════════════════════════════════════════════════════════════════
-- Phase 4: Command Chain alterations
-- ═════════════════════════════════════════════════════════════════════════════

-- ── Subtasks: add execution metadata ───────────────────────────────────────
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS phase_number INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS tool_categories JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS worker_agent_id UUID;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS quality_criteria JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS estimated_complexity VARCHAR(20) NOT NULL DEFAULT 'moderate';

CREATE INDEX IF NOT EXISTS idx_subtasks_phase ON subtasks(parent_task_id, phase_number);

-- ── Tasks: add priority ────────────────────────────────────────────────────
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority VARCHAR(20) NOT NULL DEFAULT 'normal';
```

- [ ] **Step 7: Append migration to schema.sql**

Add at the end of `src/max/db/schema.sql` (after the Phase 3 section):

```sql
-- ═════════════════════════════════════════════════════════════════════════════
-- Phase 4: Command Chain alterations
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS phase_number INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS tool_categories JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS worker_agent_id UUID;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS quality_criteria JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS estimated_complexity VARCHAR(20) NOT NULL DEFAULT 'moderate';

CREATE INDEX IF NOT EXISTS idx_subtasks_phase ON subtasks(parent_task_id, phase_number);

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority VARCHAR(20) NOT NULL DEFAULT 'normal';
```

- [ ] **Step 8: Run DB tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_postgres.py::test_subtasks_has_phase4_columns tests/test_postgres.py::test_tasks_has_priority_column -v`
Expected: PASS

- [ ] **Step 9: Run full test suite**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest --tb=short -q`
Expected: All tests pass (249+)

- [ ] **Step 10: Commit**

```bash
git add src/max/config.py src/max/db/migrations/004_command_chain.sql src/max/db/schema.sql tests/test_config.py tests/test_postgres.py
git commit -m "feat(config): add Phase 4 command chain settings and DB migration"
```

---

### Task 2: Command Chain Models

**Files:**
- Create: `src/max/command/__init__.py`
- Create: `src/max/command/models.py`
- Create: `tests/test_command_models.py`

- [ ] **Step 1: Write the failing model tests**

Create `tests/test_command_models.py`:

```python
import uuid
from datetime import UTC, datetime

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_command_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.command'`

- [ ] **Step 3: Create the command package and models**

Create `src/max/command/__init__.py`:

```python
"""Phase 4: Command Chain — Coordinator, Planner, Orchestrator pipeline."""

from max.command.models import (
    CoordinatorAction,
    CoordinatorActionType,
    ExecutionPlan,
    PlannedSubtask,
    SubtaskResult,
    WorkerConfig,
)

__all__ = [
    "CoordinatorAction",
    "CoordinatorActionType",
    "ExecutionPlan",
    "PlannedSubtask",
    "SubtaskResult",
    "WorkerConfig",
]
```

Create `src/max/command/models.py`:

```python
"""Phase 4 Command Chain models — actions, plans, configs, results."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from max.models.messages import Priority


class CoordinatorActionType(StrEnum):
    CREATE_TASK = "create_task"
    QUERY_STATUS = "query_status"
    CANCEL_TASK = "cancel_task"
    PROVIDE_CONTEXT = "provide_context"
    CLARIFICATION_RESPONSE = "clarification_response"


class CoordinatorAction(BaseModel):
    action: CoordinatorActionType
    task_id: uuid.UUID | None = None
    goal_anchor: str = ""
    priority: Priority = Priority.NORMAL
    quality_criteria: dict[str, Any] = Field(default_factory=dict)
    context_text: str = ""
    clarification_answer: str = ""
    reasoning: str = ""


class PlannedSubtask(BaseModel):
    description: str
    phase_number: int
    tool_categories: list[str] = Field(default_factory=list)
    quality_criteria: dict[str, Any] = Field(default_factory=dict)
    estimated_complexity: str = "moderate"


class ExecutionPlan(BaseModel):
    task_id: uuid.UUID
    goal_anchor: str
    subtasks: list[PlannedSubtask]
    total_phases: int
    reasoning: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkerConfig(BaseModel):
    subtask_id: uuid.UUID
    task_id: uuid.UUID
    system_prompt: str
    tool_ids: list[str] = Field(default_factory=list)
    context_package: dict[str, Any] = Field(default_factory=dict)
    quality_criteria: dict[str, Any] = Field(default_factory=dict)
    max_turns: int = 10


class SubtaskResult(BaseModel):
    subtask_id: uuid.UUID
    task_id: uuid.UUID
    success: bool
    content: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    error: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_command_models.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest --tb=short -q`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/max/command/__init__.py src/max/command/models.py tests/test_command_models.py
git commit -m "feat(command): add Phase 4 command chain models and enums"
```

---

### Task 3: TaskStore

**Files:**
- Create: `src/max/command/task_store.py`
- Create: `tests/test_task_store.py`

- [ ] **Step 1: Write the failing TaskStore tests**

Create `tests/test_task_store.py`:

```python
import uuid

import pytest

from max.command.task_store import TaskStore
from max.models.tasks import TaskStatus


@pytest.fixture
async def store(db):
    return TaskStore(db)


@pytest.mark.asyncio
async def test_create_task(store, db):
    # Create a parent intent first (FK requirement)
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) "
        "VALUES ($1, $2, $3, $4)",
        intent_id, "Test message", "telegram", "Test goal",
    )
    task = await store.create_task(
        intent_id=intent_id,
        goal_anchor="Test goal",
        priority="normal",
    )
    assert task["id"] is not None
    assert task["goal_anchor"] == "Test goal"
    assert task["status"] == "pending"
    assert task["priority"] == "normal"


@pytest.mark.asyncio
async def test_get_task(store, db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) "
        "VALUES ($1, $2, $3, $4)",
        intent_id, "Get test", "telegram", "Get goal",
    )
    created = await store.create_task(
        intent_id=intent_id, goal_anchor="Get goal", priority="high",
    )
    task = await store.get_task(created["id"])
    assert task is not None
    assert task["goal_anchor"] == "Get goal"
    assert task["priority"] == "high"


@pytest.mark.asyncio
async def test_get_task_not_found(store):
    result = await store.get_task(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_active_tasks(store, db):
    for i in range(3):
        intent_id = uuid.uuid4()
        await db.execute(
            "INSERT INTO intents (id, user_message, source_platform, goal_anchor) "
            "VALUES ($1, $2, $3, $4)",
            intent_id, f"Msg {i}", "telegram", f"Goal {i}",
        )
        await store.create_task(intent_id=intent_id, goal_anchor=f"Goal {i}")
    active = await store.get_active_tasks()
    assert len(active) >= 3


@pytest.mark.asyncio
async def test_update_task_status(store, db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) "
        "VALUES ($1, $2, $3, $4)",
        intent_id, "Status test", "telegram", "Status goal",
    )
    created = await store.create_task(intent_id=intent_id, goal_anchor="Status goal")
    await store.update_task_status(created["id"], TaskStatus.IN_PROGRESS)
    task = await store.get_task(created["id"])
    assert task["status"] == "in_progress"


@pytest.mark.asyncio
async def test_update_task_status_completed(store, db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) "
        "VALUES ($1, $2, $3, $4)",
        intent_id, "Complete test", "telegram", "Complete goal",
    )
    created = await store.create_task(intent_id=intent_id, goal_anchor="Complete goal")
    await store.update_task_status(created["id"], TaskStatus.COMPLETED)
    task = await store.get_task(created["id"])
    assert task["status"] == "completed"
    assert task["completed_at"] is not None


@pytest.mark.asyncio
async def test_create_subtask(store, db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) "
        "VALUES ($1, $2, $3, $4)",
        intent_id, "Sub test", "telegram", "Sub goal",
    )
    task = await store.create_task(intent_id=intent_id, goal_anchor="Sub goal")
    subtask = await store.create_subtask(
        task_id=task["id"],
        description="Run tests",
        phase_number=1,
        tool_categories=["code"],
        quality_criteria={"coverage": ">80%"},
        estimated_complexity="moderate",
    )
    assert subtask["description"] == "Run tests"
    assert subtask["phase_number"] == 1
    assert subtask["status"] == "pending"


@pytest.mark.asyncio
async def test_get_subtasks(store, db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) "
        "VALUES ($1, $2, $3, $4)",
        intent_id, "Multi sub", "telegram", "Multi goal",
    )
    task = await store.create_task(intent_id=intent_id, goal_anchor="Multi goal")
    await store.create_subtask(task["id"], "Step A", phase_number=1)
    await store.create_subtask(task["id"], "Step B", phase_number=1)
    await store.create_subtask(task["id"], "Step C", phase_number=2)
    subtasks = await store.get_subtasks(task["id"])
    assert len(subtasks) == 3
    # Ordered by phase_number
    assert subtasks[0]["phase_number"] <= subtasks[2]["phase_number"]


@pytest.mark.asyncio
async def test_update_subtask_result(store, db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) "
        "VALUES ($1, $2, $3, $4)",
        intent_id, "Result test", "telegram", "Result goal",
    )
    task = await store.create_task(intent_id=intent_id, goal_anchor="Result goal")
    subtask = await store.create_subtask(task["id"], "Do work", phase_number=1)
    result_data = {"content": "Done", "confidence": 0.95}
    await store.update_subtask_result(subtask["id"], result_data)
    updated = await store.get_subtasks(task["id"])
    assert updated[0]["result"] == result_data
    assert updated[0]["status"] == "completed"
    assert updated[0]["completed_at"] is not None


@pytest.mark.asyncio
async def test_update_subtask_status(store, db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) "
        "VALUES ($1, $2, $3, $4)",
        intent_id, "Status sub", "telegram", "Status sub goal",
    )
    task = await store.create_task(intent_id=intent_id, goal_anchor="Status sub goal")
    subtask = await store.create_subtask(task["id"], "A subtask", phase_number=1)
    await store.update_subtask_status(subtask["id"], TaskStatus.IN_PROGRESS)
    subs = await store.get_subtasks(task["id"])
    assert subs[0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_create_result(store, db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) "
        "VALUES ($1, $2, $3, $4)",
        intent_id, "Result create", "telegram", "Result create goal",
    )
    task = await store.create_task(intent_id=intent_id, goal_anchor="Result create goal")
    result_id = await store.create_result(
        task_id=task["id"], content="Final answer", confidence=0.9,
    )
    assert result_id is not None
    row = await db.fetchone("SELECT * FROM results WHERE id = $1", result_id)
    assert row["content"] == "Final answer"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_task_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.command.task_store'`

- [ ] **Step 3: Implement TaskStore**

Create `src/max/command/task_store.py`:

```python
"""TaskStore — async CRUD for tasks and subtasks over PostgreSQL."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from max.db.postgres import Database
from max.models.tasks import TaskStatus

logger = logging.getLogger(__name__)


class TaskStore:
    """Thin persistence layer for Task and SubTask operations."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_task(
        self,
        intent_id: uuid.UUID,
        goal_anchor: str,
        priority: str = "normal",
        quality_criteria: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new task and return its row as a dict."""
        task_id = uuid.uuid4()
        criteria = json.dumps(quality_criteria or {})
        await self._db.execute(
            "INSERT INTO tasks (id, goal_anchor, source_intent_id, status, priority, quality_criteria) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            task_id, goal_anchor, intent_id, "pending", priority, criteria,
        )
        return await self.get_task(task_id)  # type: ignore[return-value]

    async def get_task(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        """Get a task by ID."""
        return await self._db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)

    async def get_active_tasks(self) -> list[dict[str, Any]]:
        """Get all non-terminal tasks."""
        return await self._db.fetchall(
            "SELECT * FROM tasks WHERE status NOT IN ('completed', 'failed') "
            "ORDER BY created_at DESC"
        )

    async def update_task_status(
        self,
        task_id: uuid.UUID,
        status: TaskStatus,
    ) -> None:
        """Update a task's status. Sets completed_at for terminal states."""
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            await self._db.execute(
                "UPDATE tasks SET status = $1, completed_at = $2 WHERE id = $3",
                status.value, datetime.now(UTC), task_id,
            )
        else:
            await self._db.execute(
                "UPDATE tasks SET status = $1 WHERE id = $2",
                status.value, task_id,
            )

    async def create_subtask(
        self,
        task_id: uuid.UUID,
        description: str,
        phase_number: int = 0,
        tool_categories: list[str] | None = None,
        quality_criteria: dict[str, Any] | None = None,
        estimated_complexity: str = "moderate",
    ) -> dict[str, Any]:
        """Create a subtask and return its row."""
        subtask_id = uuid.uuid4()
        cats = json.dumps(tool_categories or [])
        criteria = json.dumps(quality_criteria or {})
        await self._db.execute(
            "INSERT INTO subtasks "
            "(id, parent_task_id, description, phase_number, tool_categories, "
            "quality_criteria, estimated_complexity) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)",
            subtask_id, task_id, description, phase_number,
            cats, criteria, estimated_complexity,
        )
        row = await self._db.fetchone("SELECT * FROM subtasks WHERE id = $1", subtask_id)
        return row  # type: ignore[return-value]

    async def get_subtasks(self, task_id: uuid.UUID) -> list[dict[str, Any]]:
        """Get all subtasks for a task, ordered by phase then creation time."""
        return await self._db.fetchall(
            "SELECT * FROM subtasks WHERE parent_task_id = $1 "
            "ORDER BY phase_number, created_at",
            task_id,
        )

    async def update_subtask_status(
        self,
        subtask_id: uuid.UUID,
        status: TaskStatus,
    ) -> None:
        """Update a subtask's status."""
        if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            await self._db.execute(
                "UPDATE subtasks SET status = $1, completed_at = $2 WHERE id = $3",
                status.value, datetime.now(UTC), subtask_id,
            )
        else:
            await self._db.execute(
                "UPDATE subtasks SET status = $1 WHERE id = $2",
                status.value, subtask_id,
            )

    async def update_subtask_result(
        self,
        subtask_id: uuid.UUID,
        result_data: dict[str, Any],
    ) -> None:
        """Write the result to a subtask and mark it completed."""
        await self._db.execute(
            "UPDATE subtasks SET result = $1::jsonb, status = 'completed', "
            "completed_at = $2 WHERE id = $3",
            json.dumps(result_data), datetime.now(UTC), subtask_id,
        )

    async def create_result(
        self,
        task_id: uuid.UUID,
        content: str,
        confidence: float,
        artifacts: list[str] | None = None,
    ) -> uuid.UUID:
        """Create a Result record and return its ID."""
        result_id = uuid.uuid4()
        arts = json.dumps(artifacts or [])
        await self._db.execute(
            "INSERT INTO results (id, task_id, content, confidence, artifacts) "
            "VALUES ($1, $2, $3, $4, $5::jsonb)",
            result_id, task_id, content, confidence, arts,
        )
        return result_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_task_store.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest --tb=short -q`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/max/command/task_store.py tests/test_task_store.py
git commit -m "feat(command): add TaskStore for task/subtask CRUD over PostgreSQL"
```

---

### Task 4: WorkerAgent and AgentRunner

**Files:**
- Create: `src/max/command/worker.py`
- Create: `src/max/command/runner.py`
- Create: `tests/test_worker.py`
- Create: `tests/test_runner.py`

- [ ] **Step 1: Write the failing WorkerAgent tests**

Create `tests/test_worker.py`:

```python
import uuid
from unittest.mock import AsyncMock

import pytest

from max.command.worker import WorkerAgent, WORKER_SYSTEM_PROMPT_TEMPLATE
from max.llm.models import LLMResponse, ModelType


def _make_llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


class TestWorkerAgent:
    @pytest.mark.asyncio
    async def test_run_success(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_make_llm_response(
            '{"content": "The answer is 42", "confidence": 0.9, "reasoning": "Calculated"}'
        ))
        worker = WorkerAgent(
            llm=llm,
            system_prompt="You are a worker.",
            model=ModelType.OPUS,
            max_turns=10,
        )
        result = await worker.run({
            "subtask_id": str(uuid.uuid4()),
            "task_id": str(uuid.uuid4()),
            "description": "Calculate the answer",
            "context_package": {},
            "quality_criteria": {},
        })
        assert result["success"] is True
        assert result["content"] == "The answer is 42"
        assert result["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_run_json_in_markdown_block(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_make_llm_response(
            '```json\n{"content": "Result", "confidence": 0.8, "reasoning": "Done"}\n```'
        ))
        worker = WorkerAgent(
            llm=llm,
            system_prompt="You are a worker.",
            model=ModelType.OPUS,
        )
        result = await worker.run({
            "subtask_id": str(uuid.uuid4()),
            "task_id": str(uuid.uuid4()),
            "description": "Do something",
        })
        assert result["success"] is True
        assert result["content"] == "Result"

    @pytest.mark.asyncio
    async def test_run_llm_returns_plain_text(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_make_llm_response(
            "Here is the answer to your question about Python features."
        ))
        worker = WorkerAgent(
            llm=llm,
            system_prompt="You are a worker.",
            model=ModelType.OPUS,
        )
        result = await worker.run({
            "subtask_id": str(uuid.uuid4()),
            "task_id": str(uuid.uuid4()),
            "description": "Research Python",
        })
        assert result["success"] is True
        assert "Python features" in result["content"]
        assert result["confidence"] == 0.5  # fallback confidence

    @pytest.mark.asyncio
    async def test_run_llm_exception(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("API down"))
        worker = WorkerAgent(
            llm=llm,
            system_prompt="You are a worker.",
            model=ModelType.OPUS,
        )
        result = await worker.run({
            "subtask_id": str(uuid.uuid4()),
            "task_id": str(uuid.uuid4()),
            "description": "Do work",
        })
        assert result["success"] is False
        assert "API down" in result["error"]


class TestWorkerSystemPromptTemplate:
    def test_template_contains_placeholders(self):
        assert "{description}" in WORKER_SYSTEM_PROMPT_TEMPLATE
        assert "{context_summary}" in WORKER_SYSTEM_PROMPT_TEMPLATE
        assert "{quality_criteria}" in WORKER_SYSTEM_PROMPT_TEMPLATE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.command.worker'`

- [ ] **Step 3: Implement WorkerAgent**

Create `src/max/command/worker.py`:

```python
"""WorkerAgent — generic ephemeral subtask executor."""

from __future__ import annotations

import json
import logging
from typing import Any

from max.agents.base import AgentConfig, BaseAgent
from max.llm.client import LLMClient
from max.llm.models import ModelType

logger = logging.getLogger(__name__)

WORKER_SYSTEM_PROMPT_TEMPLATE = """You are a worker agent for Max, an autonomous AI system.

Your task:
{description}

Context:
{context_summary}

Quality criteria:
{quality_criteria}

Return ONLY valid JSON:
{{
  "content": "Your work product — the full result of the subtask",
  "confidence": 0.0 to 1.0,
  "reasoning": "Brief explanation of your approach"
}}"""


class WorkerAgent(BaseAgent):
    """Ephemeral agent that executes a single subtask via LLM reasoning."""

    def __init__(
        self,
        llm: LLMClient,
        system_prompt: str,
        model: ModelType = ModelType.OPUS,
        max_turns: int = 10,
    ) -> None:
        config = AgentConfig(
            name="worker",
            system_prompt=system_prompt,
            model=model,
            max_turns=max_turns,
        )
        super().__init__(config=config, llm=llm)

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute the subtask and return a result dict.

        input_data keys:
            subtask_id, task_id, description, context_package, quality_criteria
        """
        description = input_data.get("description", "")
        context_pkg = input_data.get("context_package", {})
        quality = input_data.get("quality_criteria", {})

        context_summary = json.dumps(context_pkg, indent=2) if context_pkg else "None provided"
        quality_str = json.dumps(quality, indent=2) if quality else "None specified"

        prompt = WORKER_SYSTEM_PROMPT_TEMPLATE.format(
            description=description,
            context_summary=context_summary,
            quality_criteria=quality_str,
        )

        self.reset()
        try:
            response = await self.think(
                messages=[{"role": "user", "content": f"Execute this subtask: {description}"}],
                system_prompt=prompt,
            )
            parsed = self._parse_response(response.text)
            return {
                "success": True,
                "content": parsed.get("content", response.text),
                "confidence": parsed.get("confidence", 0.5),
                "reasoning": parsed.get("reasoning", ""),
                "error": None,
            }
        except Exception as exc:
            logger.exception("Worker failed executing subtask")
            return {
                "success": False,
                "content": "",
                "confidence": 0.0,
                "reasoning": "",
                "error": str(exc),
            }

    @staticmethod
    def _parse_response(text: str) -> dict[str, Any]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except (json.JSONDecodeError, ValueError):
                    continue
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"content": text, "confidence": 0.5, "reasoning": ""}
```

- [ ] **Step 4: Run worker tests**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_worker.py -v`
Expected: All PASS

- [ ] **Step 5: Write the failing AgentRunner tests**

Create `tests/test_runner.py`:

```python
import uuid
from unittest.mock import AsyncMock

import pytest

from max.agents.base import AgentContext
from max.command.runner import AgentRunner, InProcessRunner
from max.command.models import WorkerConfig, SubtaskResult
from max.llm.models import LLMResponse, ModelType


def _make_llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


class TestInProcessRunner:
    @pytest.mark.asyncio
    async def test_run_success(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_make_llm_response(
            '{"content": "Done", "confidence": 0.85, "reasoning": "Simple task"}'
        ))
        runner = InProcessRunner(llm=llm)
        config = WorkerConfig(
            subtask_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            system_prompt="You are a worker.",
        )
        context = AgentContext()
        result = await runner.run(config, context)
        assert isinstance(result, SubtaskResult)
        assert result.success is True
        assert result.content == "Done"
        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_run_failure(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=RuntimeError("LLM error"))
        runner = InProcessRunner(llm=llm)
        config = WorkerConfig(
            subtask_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            system_prompt="You are a worker.",
        )
        context = AgentContext()
        result = await runner.run(config, context)
        assert isinstance(result, SubtaskResult)
        assert result.success is False
        assert "LLM error" in result.error

    @pytest.mark.asyncio
    async def test_run_with_custom_model(self):
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_make_llm_response(
            '{"content": "OK", "confidence": 0.7, "reasoning": "Worked"}'
        ))
        runner = InProcessRunner(llm=llm, default_model=ModelType.SONNET)
        config = WorkerConfig(
            subtask_id=uuid.uuid4(),
            task_id=uuid.uuid4(),
            system_prompt="You are a worker.",
        )
        result = await runner.run(config, AgentContext())
        assert result.success is True


class TestAgentRunnerIsAbstract:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            AgentRunner()  # type: ignore[abstract]
```

- [ ] **Step 6: Implement AgentRunner**

Create `src/max/command/runner.py`:

```python
"""AgentRunner — abstraction for agent execution (in-process or subprocess)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from max.agents.base import AgentContext
from max.command.models import SubtaskResult, WorkerConfig
from max.command.worker import WorkerAgent
from max.llm.client import LLMClient
from max.llm.models import ModelType

logger = logging.getLogger(__name__)


class AgentRunner(ABC):
    """Abstract interface for running worker agents."""

    @abstractmethod
    async def run(
        self,
        worker_config: WorkerConfig,
        context: AgentContext,
    ) -> SubtaskResult:
        """Run a worker agent with the given config and return its result."""


class InProcessRunner(AgentRunner):
    """Runs worker agents in the current process as asyncio tasks."""

    def __init__(
        self,
        llm: LLMClient,
        default_model: ModelType = ModelType.OPUS,
    ) -> None:
        self._llm = llm
        self._default_model = default_model

    async def run(
        self,
        worker_config: WorkerConfig,
        context: AgentContext,
    ) -> SubtaskResult:
        """Create a WorkerAgent, execute, and wrap the result."""
        worker = WorkerAgent(
            llm=self._llm,
            system_prompt=worker_config.system_prompt,
            model=self._default_model,
            max_turns=worker_config.max_turns,
        )
        raw = await worker.run({
            "subtask_id": str(worker_config.subtask_id),
            "task_id": str(worker_config.task_id),
            "description": worker_config.system_prompt,
            "context_package": worker_config.context_package,
            "quality_criteria": worker_config.quality_criteria,
        })
        return SubtaskResult(
            subtask_id=worker_config.subtask_id,
            task_id=worker_config.task_id,
            success=raw.get("success", False),
            content=raw.get("content", ""),
            confidence=raw.get("confidence", 0.0),
            reasoning=raw.get("reasoning", ""),
            error=raw.get("error"),
        )
```

- [ ] **Step 7: Run runner tests**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_runner.py -v`
Expected: All PASS

- [ ] **Step 8: Run full test suite**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest --tb=short -q`
Expected: All tests pass

- [ ] **Step 9: Commit**

```bash
git add src/max/command/worker.py src/max/command/runner.py tests/test_worker.py tests/test_runner.py
git commit -m "feat(command): add WorkerAgent and AgentRunner abstraction"
```

---

### Task 5: Coordinator Agent

**Files:**
- Create: `src/max/command/coordinator.py`
- Create: `tests/test_coordinator.py`

- [ ] **Step 1: Write the failing Coordinator tests**

Create `tests/test_coordinator.py`:

```python
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.command.coordinator import CoordinatorAgent, ROUTING_SYSTEM_PROMPT
from max.command.models import CoordinatorActionType
from max.agents.base import AgentConfig
from max.config import Settings
from max.llm.models import LLMResponse, ModelType
from max.models.messages import Priority
from max.models.tasks import TaskStatus


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_llm_response(action_dict: dict) -> LLMResponse:
    return LLMResponse(
        text=json.dumps(action_dict),
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


def _make_coordinator(llm, bus, db, warm, settings):
    config = AgentConfig(
        name="coordinator",
        system_prompt="",
        model=ModelType.OPUS,
    )
    state_mgr = AsyncMock()
    state_mgr.load = AsyncMock(return_value=MagicMock(
        active_tasks=[], task_queue=[], model_dump=MagicMock(return_value={}),
    ))
    state_mgr.save = AsyncMock()
    task_store = AsyncMock()
    return CoordinatorAgent(
        config=config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm,
        settings=settings,
        state_manager=state_mgr,
        task_store=task_store,
    )


class TestCoordinatorClassification:
    @pytest.mark.asyncio
    async def test_create_task_action(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        llm.complete = AsyncMock(return_value=_make_llm_response({
            "action": "create_task",
            "goal_anchor": "Deploy the app",
            "priority": "high",
            "quality_criteria": {},
            "reasoning": "New deployment request",
        }))

        coord = _make_coordinator(llm, bus, db, warm, settings)
        coord._task_store.create_task = AsyncMock(return_value={
            "id": uuid.uuid4(), "goal_anchor": "Deploy the app",
            "status": "pending", "priority": "high",
        })

        intent_data = {
            "id": str(uuid.uuid4()),
            "user_message": "Deploy the app to staging",
            "source_platform": "telegram",
            "goal_anchor": "Deploy the app",
            "priority": "high",
        }
        await coord.on_intent("intents.new", intent_data)

        # Should publish status update and tasks.plan
        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "status_updates.new" in channels
        assert "tasks.plan" in channels

    @pytest.mark.asyncio
    async def test_query_status_action(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        llm.complete = AsyncMock(return_value=_make_llm_response({
            "action": "query_status",
            "reasoning": "User asking about progress",
        }))

        coord = _make_coordinator(llm, bus, db, warm, settings)
        intent_data = {
            "id": str(uuid.uuid4()),
            "user_message": "What are you working on?",
            "source_platform": "telegram",
            "goal_anchor": "What are you working on?",
            "priority": "normal",
        }
        await coord.on_intent("intents.new", intent_data)

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "status_updates.new" in channels
        # Should NOT publish tasks.plan
        assert "tasks.plan" not in channels

    @pytest.mark.asyncio
    async def test_cancel_task_action(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        llm.complete = AsyncMock(return_value=_make_llm_response({
            "action": "cancel_task",
            "task_id": str(task_id),
            "reasoning": "User wants to cancel",
        }))

        coord = _make_coordinator(llm, bus, db, warm, settings)
        coord._state_manager.load = AsyncMock(return_value=MagicMock(
            active_tasks=[MagicMock(task_id=task_id, goal_anchor="Deploy")],
            task_queue=[],
            model_dump=MagicMock(return_value={}),
        ))
        coord._task_store.update_task_status = AsyncMock()

        intent_data = {
            "id": str(uuid.uuid4()),
            "user_message": "Cancel that",
            "source_platform": "telegram",
            "goal_anchor": "Cancel that",
            "priority": "normal",
        }
        await coord.on_intent("intents.new", intent_data)

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "tasks.cancel" in channels
        coord._task_store.update_task_status.assert_called_once()


class TestCoordinatorTaskComplete:
    @pytest.mark.asyncio
    async def test_on_task_complete_success(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        coord = _make_coordinator(llm, bus, db, warm, settings)
        task_id = uuid.uuid4()
        coord._task_store.update_task_status = AsyncMock()
        coord._task_store.get_task = AsyncMock(return_value={
            "id": task_id, "goal_anchor": "Deploy the app",
        })

        await coord.on_task_complete("tasks.complete", {
            "task_id": str(task_id),
            "success": True,
            "result_content": "Deployed successfully",
            "confidence": 0.95,
        })

        coord._task_store.update_task_status.assert_called_once_with(
            task_id, TaskStatus.COMPLETED
        )
        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "results.new" in channels

    @pytest.mark.asyncio
    async def test_on_task_complete_failure(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        coord = _make_coordinator(llm, bus, db, warm, settings)
        task_id = uuid.uuid4()
        coord._task_store.update_task_status = AsyncMock()
        coord._task_store.get_task = AsyncMock(return_value={
            "id": task_id, "goal_anchor": "Deploy the app",
        })

        await coord.on_task_complete("tasks.complete", {
            "task_id": str(task_id),
            "success": False,
            "error": "All subtasks failed",
        })

        coord._task_store.update_task_status.assert_called_once_with(
            task_id, TaskStatus.FAILED
        )
        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "results.new" in channels


class TestCoordinatorLifecycle:
    @pytest.mark.asyncio
    async def test_start_subscribes_to_channels(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        coord = _make_coordinator(llm, bus, db, warm, settings)
        await coord.start()

        subscribe_calls = bus.subscribe.call_args_list
        channels = [c[0][0] for c in subscribe_calls]
        assert "intents.new" in channels
        assert "tasks.complete" in channels

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        coord = _make_coordinator(llm, bus, db, warm, settings)
        await coord.start()
        await coord.stop()

        unsub_calls = bus.unsubscribe.call_args_list
        channels = [c[0][0] for c in unsub_calls]
        assert "intents.new" in channels
        assert "tasks.complete" in channels


class TestCoordinatorParsing:
    @pytest.mark.asyncio
    async def test_parse_llm_response_json(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()
        coord = _make_coordinator(llm, bus, db, warm, settings)

        result = coord._parse_action_response('{"action": "query_status", "reasoning": "test"}')
        assert result.action == CoordinatorActionType.QUERY_STATUS

    @pytest.mark.asyncio
    async def test_parse_llm_response_markdown(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()
        coord = _make_coordinator(llm, bus, db, warm, settings)

        result = coord._parse_action_response(
            '```json\n{"action": "create_task", "goal_anchor": "Test", "reasoning": "ok"}\n```'
        )
        assert result.action == CoordinatorActionType.CREATE_TASK
        assert result.goal_anchor == "Test"


class TestRoutingSystemPrompt:
    def test_prompt_contains_action_types(self):
        assert "create_task" in ROUTING_SYSTEM_PROMPT
        assert "query_status" in ROUTING_SYSTEM_PROMPT
        assert "cancel_task" in ROUTING_SYSTEM_PROMPT
        assert "provide_context" in ROUTING_SYSTEM_PROMPT
        assert "clarification_response" in ROUTING_SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_coordinator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.command.coordinator'`

- [ ] **Step 3: Implement CoordinatorAgent**

Create `src/max/command/coordinator.py`:

```python
"""CoordinatorAgent — intent classification, routing, state management."""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from typing import Any

from max.agents.base import AgentConfig, AgentContext, BaseAgent
from max.command.models import CoordinatorAction, CoordinatorActionType
from max.command.task_store import TaskStore
from max.config import Settings
from max.llm.client import LLMClient
from max.memory.coordinator_state import CoordinatorStateManager
from max.memory.models import ActiveTaskSummary
from max.models.messages import Priority
from max.models.tasks import TaskStatus

logger = logging.getLogger(__name__)

ROUTING_SYSTEM_PROMPT = """You are the Coordinator for Max, an autonomous AI agent system.
Your job is to classify user intents and decide what action to take.

Current state:
{state_summary}

Classify the intent into exactly ONE action. Return ONLY valid JSON:
{{
  "action": "create_task | query_status | cancel_task | provide_context | clarification_response",
  "goal_anchor": "one-sentence summary of what user wants (for create_task)",
  "priority": "low | normal | high | urgent (for create_task)",
  "task_id": "UUID of relevant task (for cancel_task, provide_context, clarification_response)",
  "quality_criteria": {{}} ,
  "context_text": "additional context (for provide_context)",
  "clarification_answer": "user's answer (for clarification_response)",
  "reasoning": "brief explanation of your classification"
}}

Action guidelines:
- create_task: User wants something done. New work request.
- query_status: User asking about progress or current tasks.
- cancel_task: User wants to stop/cancel a task. Use most recent active task if not specified.
- provide_context: User is adding info to an existing in-progress task.
- clarification_response: User is answering a question Max asked them."""


class CoordinatorAgent(BaseAgent):
    """Central routing agent — classifies intents and manages task lifecycle."""

    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        bus: Any,
        db: Any,
        warm_memory: Any,
        settings: Settings,
        state_manager: CoordinatorStateManager,
        task_store: TaskStore,
    ) -> None:
        context = AgentContext(bus=bus, db=db, warm_memory=warm_memory)
        super().__init__(config=config, llm=llm, context=context)
        self._bus = bus
        self._db = db
        self._warm = warm_memory
        self._settings = settings
        self._state_manager = state_manager
        self._task_store = task_store

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """BaseAgent abstract method — not used directly."""
        return {}

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to bus channels."""
        await self._bus.subscribe("intents.new", self.on_intent)
        await self._bus.subscribe("tasks.complete", self.on_task_complete)
        await self.on_start()
        logger.info("CoordinatorAgent started")

    async def stop(self) -> None:
        """Unsubscribe from bus channels."""
        await self._bus.unsubscribe("intents.new", self.on_intent)
        await self._bus.unsubscribe("tasks.complete", self.on_task_complete)
        await self.on_stop()
        logger.info("CoordinatorAgent stopped")

    # ── Bus handlers ────────────────────────────────────────────────────

    async def on_intent(self, channel: str, data: dict[str, Any]) -> None:
        """Handle a new intent from the Communicator."""
        state = await self._state_manager.load()

        # Build state summary for LLM context
        state_summary = self._build_state_summary(state)

        # Classify the intent via LLM
        prompt = ROUTING_SYSTEM_PROMPT.format(state_summary=state_summary)
        user_message = data.get("user_message", "")

        self.reset()
        try:
            response = await self.think(
                messages=[{"role": "user", "content": user_message}],
                system_prompt=prompt,
            )
            action = self._parse_action_response(response.text)
        except Exception:
            logger.exception("Coordinator classification failed")
            action = CoordinatorAction(
                action=CoordinatorActionType.CREATE_TASK,
                goal_anchor=data.get("goal_anchor", user_message),
                priority=Priority(data.get("priority", "normal")),
                reasoning="Fallback: classification failed",
            )

        # Route based on action type
        if action.action == CoordinatorActionType.CREATE_TASK:
            await self._handle_create_task(action, data, state)
        elif action.action == CoordinatorActionType.QUERY_STATUS:
            await self._handle_query_status(state)
        elif action.action == CoordinatorActionType.CANCEL_TASK:
            await self._handle_cancel_task(action, state)
        elif action.action == CoordinatorActionType.PROVIDE_CONTEXT:
            await self._handle_provide_context(action)
        elif action.action == CoordinatorActionType.CLARIFICATION_RESPONSE:
            await self._handle_clarification_response(action)

        await self._state_manager.save(state)

    async def on_task_complete(self, channel: str, data: dict[str, Any]) -> None:
        """Handle task completion from the Orchestrator."""
        task_id = uuid_mod.UUID(data["task_id"])
        success = data.get("success", False)

        if success:
            await self._task_store.update_task_status(task_id, TaskStatus.COMPLETED)
        else:
            await self._task_store.update_task_status(task_id, TaskStatus.FAILED)

        task = await self._task_store.get_task(task_id)
        goal = task["goal_anchor"] if task else "Unknown task"

        # Publish result to Communicator
        result_data = {
            "id": str(uuid_mod.uuid4()),
            "task_id": str(task_id),
            "content": data.get("result_content", data.get("error", "Task completed")),
            "confidence": data.get("confidence", 1.0 if success else 0.0),
            "artifacts": [],
        }
        await self._bus.publish("results.new", result_data)

        # Update state
        state = await self._state_manager.load()
        state.active_tasks = [
            t for t in state.active_tasks if t.task_id != task_id
        ]
        await self._state_manager.save(state)

    # ── Action handlers ─────────────────────────────────────────────────

    async def _handle_create_task(
        self,
        action: CoordinatorAction,
        intent_data: dict[str, Any],
        state: Any,
    ) -> None:
        """Create a task and route to Planner."""
        intent_id = uuid_mod.UUID(intent_data["id"])
        task = await self._task_store.create_task(
            intent_id=intent_id,
            goal_anchor=action.goal_anchor or intent_data.get("goal_anchor", ""),
            priority=action.priority.value,
            quality_criteria=action.quality_criteria,
        )

        task_id = task["id"]
        await self._task_store.update_task_status(task_id, TaskStatus.PLANNING)

        # Update state
        state.active_tasks.append(ActiveTaskSummary(
            task_id=task_id,
            goal_anchor=task["goal_anchor"],
            status=TaskStatus.PLANNING,
            priority=Priority(action.priority),
        ))

        # Notify user
        await self._bus.publish("status_updates.new", {
            "id": str(uuid_mod.uuid4()),
            "task_id": str(task_id),
            "message": f"Planning: {task['goal_anchor']}",
            "progress": 0.0,
        })

        # Route to Planner
        await self._bus.publish("tasks.plan", {
            "task_id": str(task_id),
            "goal_anchor": task["goal_anchor"],
            "priority": action.priority.value,
            "quality_criteria": action.quality_criteria,
        })

    async def _handle_query_status(self, state: Any) -> None:
        """Respond with current task status."""
        if not state.active_tasks:
            message = "No active tasks. I'm idle and ready for work."
        else:
            lines = ["Current tasks:"]
            for t in state.active_tasks:
                lines.append(f"- [{t.status}] {t.goal_anchor}")
            message = "\n".join(lines)

        await self._bus.publish("status_updates.new", {
            "id": str(uuid_mod.uuid4()),
            "task_id": str(uuid_mod.uuid4()),
            "message": message,
            "progress": 0.0,
        })

    async def _handle_cancel_task(
        self,
        action: CoordinatorAction,
        state: Any,
    ) -> None:
        """Cancel a task."""
        task_id = action.task_id
        if task_id is None and state.active_tasks:
            task_id = state.active_tasks[-1].task_id

        if task_id is None:
            await self._bus.publish("status_updates.new", {
                "id": str(uuid_mod.uuid4()),
                "task_id": str(uuid_mod.uuid4()),
                "message": "No active task to cancel.",
                "progress": 0.0,
            })
            return

        await self._task_store.update_task_status(task_id, TaskStatus.FAILED)
        await self._bus.publish("tasks.cancel", {"task_id": str(task_id)})

        goal = "Unknown"
        for t in state.active_tasks:
            if t.task_id == task_id:
                goal = t.goal_anchor
                break
        state.active_tasks = [t for t in state.active_tasks if t.task_id != task_id]

        await self._bus.publish("status_updates.new", {
            "id": str(uuid_mod.uuid4()),
            "task_id": str(task_id),
            "message": f"Cancelled: {goal}",
            "progress": 0.0,
        })

    async def _handle_provide_context(self, action: CoordinatorAction) -> None:
        """Forward additional context to Planner/Orchestrator."""
        if action.task_id:
            await self._bus.publish("tasks.context_update", {
                "task_id": str(action.task_id),
                "context_text": action.context_text,
            })

    async def _handle_clarification_response(self, action: CoordinatorAction) -> None:
        """Forward clarification answer to the Planner."""
        if action.task_id:
            await self._bus.publish("clarifications.response", {
                "task_id": str(action.task_id),
                "answer": action.clarification_answer,
            })

    # ── Helpers ──────────────────────────────────────────────────────────

    def _build_state_summary(self, state: Any) -> str:
        """Build a text summary of the coordinator state for LLM context."""
        if not state.active_tasks:
            return "No active tasks. System is idle."
        lines = [f"Active tasks ({len(state.active_tasks)}):"]
        for t in state.active_tasks:
            lines.append(
                f"- [{t.status}] {t.goal_anchor} (priority={t.priority})"
            )
        if state.task_queue:
            lines.append(f"\nQueued tasks: {len(state.task_queue)}")
        return "\n".join(lines)

    @staticmethod
    def _parse_action_response(text: str) -> CoordinatorAction:
        """Parse LLM JSON into a CoordinatorAction."""
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    data = json.loads(part)
                    return CoordinatorAction.model_validate(data)
                except (json.JSONDecodeError, ValueError):
                    continue
        try:
            data = json.loads(text)
            return CoordinatorAction.model_validate(data)
        except (json.JSONDecodeError, ValueError):
            return CoordinatorAction(
                action=CoordinatorActionType.CREATE_TASK,
                goal_anchor=text[:200] if text else "Unknown",
                reasoning="Fallback: could not parse LLM response",
            )
```

- [ ] **Step 4: Run coordinator tests**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_coordinator.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest --tb=short -q`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/max/command/coordinator.py tests/test_coordinator.py
git commit -m "feat(command): add CoordinatorAgent with intent classification and routing"
```

---

### Task 6: Planner Agent

**Files:**
- Create: `src/max/command/planner.py`
- Create: `tests/test_planner.py`

- [ ] **Step 1: Write the failing Planner tests**

Create `tests/test_planner.py`:

```python
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.command.planner import PlannerAgent, PLANNING_SYSTEM_PROMPT
from max.command.models import ExecutionPlan, PlannedSubtask
from max.agents.base import AgentConfig
from max.config import Settings
from max.llm.models import LLMResponse, ModelType


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_llm_response(data: dict) -> LLMResponse:
    return LLMResponse(
        text=json.dumps(data),
        input_tokens=200,
        output_tokens=100,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


def _make_planner(llm, bus, db, warm, settings):
    config = AgentConfig(name="planner", system_prompt="", model=ModelType.OPUS)
    task_store = AsyncMock()
    return PlannerAgent(
        config=config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm,
        settings=settings,
        task_store=task_store,
    )


class TestPlannerDecomposition:
    @pytest.mark.asyncio
    async def test_successful_decomposition(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()
        llm.complete = AsyncMock(return_value=_make_llm_response({
            "subtasks": [
                {"description": "Research topic", "phase_number": 1,
                 "tool_categories": [], "quality_criteria": {}, "estimated_complexity": "low"},
                {"description": "Write summary", "phase_number": 2,
                 "tool_categories": [], "quality_criteria": {}, "estimated_complexity": "moderate"},
            ],
            "needs_clarification": False,
            "reasoning": "Two-phase approach: research then summarize",
        }))

        planner = _make_planner(llm, bus, db, warm, settings)
        planner._task_store.create_subtask = AsyncMock(side_effect=[
            {"id": uuid.uuid4(), "description": "Research topic", "phase_number": 1, "status": "pending"},
            {"id": uuid.uuid4(), "description": "Write summary", "phase_number": 2, "status": "pending"},
        ])

        await planner.on_task_plan("tasks.plan", {
            "task_id": str(task_id),
            "goal_anchor": "Research Python 3.13",
            "priority": "normal",
            "quality_criteria": {},
        })

        # Should publish execution plan
        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "tasks.execute" in channels

        # Verify the plan payload
        plan_call = next(c for c in calls if c[0][0] == "tasks.execute")
        plan_data = plan_call[0][1]
        assert plan_data["task_id"] == str(task_id)
        assert len(plan_data["subtasks"]) == 2
        assert plan_data["total_phases"] == 2

    @pytest.mark.asyncio
    async def test_clarification_needed(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        llm.complete = AsyncMock(return_value=_make_llm_response({
            "subtasks": [],
            "needs_clarification": True,
            "clarification_question": "Which app do you want deployed?",
            "clarification_options": ["App A", "App B"],
            "reasoning": "Ambiguous target",
        }))

        planner = _make_planner(llm, bus, db, warm, settings)
        task_id = uuid.uuid4()

        await planner.on_task_plan("tasks.plan", {
            "task_id": str(task_id),
            "goal_anchor": "Deploy the thing",
            "priority": "normal",
            "quality_criteria": {},
        })

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "clarifications.new" in channels
        assert "tasks.execute" not in channels

        # Verify task_id stored in pending clarifications
        assert task_id in planner._pending_clarifications


class TestPlannerClarificationResume:
    @pytest.mark.asyncio
    async def test_resume_after_clarification(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        task_id = uuid.uuid4()

        # Second call (after clarification) returns a plan
        llm.complete = AsyncMock(return_value=_make_llm_response({
            "subtasks": [
                {"description": "Deploy App A", "phase_number": 1,
                 "tool_categories": [], "quality_criteria": {}, "estimated_complexity": "moderate"},
            ],
            "needs_clarification": False,
            "reasoning": "Clear after clarification",
        }))

        planner = _make_planner(llm, bus, db, warm, settings)
        planner._task_store.create_subtask = AsyncMock(return_value={
            "id": uuid.uuid4(), "description": "Deploy App A", "phase_number": 1, "status": "pending",
        })

        # Simulate pending clarification
        planner._pending_clarifications[task_id] = {
            "goal_anchor": "Deploy the thing",
            "priority": "normal",
            "quality_criteria": {},
        }

        await planner.on_clarification_response("clarifications.response", {
            "task_id": str(task_id),
            "answer": "App A to staging",
        })

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "tasks.execute" in channels
        assert task_id not in planner._pending_clarifications


class TestPlannerLifecycle:
    @pytest.mark.asyncio
    async def test_start_subscribes(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        planner = _make_planner(llm, bus, db, warm, settings)
        await planner.start()

        channels = [c[0][0] for c in bus.subscribe.call_args_list]
        assert "tasks.plan" in channels
        assert "clarifications.response" in channels
        assert "tasks.context_update" in channels

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        planner = _make_planner(llm, bus, db, warm, settings)
        await planner.start()
        await planner.stop()

        channels = [c[0][0] for c in bus.unsubscribe.call_args_list]
        assert "tasks.plan" in channels
        assert "clarifications.response" in channels


class TestPlannerMaxSubtasks:
    @pytest.mark.asyncio
    async def test_subtasks_capped_at_max(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("POSTGRES_PASSWORD", "test")
        monkeypatch.setenv("PLANNER_MAX_SUBTASKS", "3")
        settings = Settings()
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()

        # LLM returns 5 subtasks but max is 3
        llm.complete = AsyncMock(return_value=_make_llm_response({
            "subtasks": [
                {"description": f"Step {i}", "phase_number": 1,
                 "tool_categories": [], "quality_criteria": {}, "estimated_complexity": "low"}
                for i in range(5)
            ],
            "needs_clarification": False,
            "reasoning": "Many steps",
        }))

        planner = _make_planner(llm, bus, db, warm, settings)
        planner._task_store.create_subtask = AsyncMock(return_value={
            "id": uuid.uuid4(), "description": "Step", "phase_number": 1, "status": "pending",
        })

        await planner.on_task_plan("tasks.plan", {
            "task_id": str(uuid.uuid4()),
            "goal_anchor": "Big task",
            "priority": "normal",
            "quality_criteria": {},
        })

        # Only 3 subtasks should have been created
        assert planner._task_store.create_subtask.call_count == 3


class TestPlanningSystemPrompt:
    def test_prompt_has_required_fields(self):
        assert "subtasks" in PLANNING_SYSTEM_PROMPT
        assert "phase_number" in PLANNING_SYSTEM_PROMPT
        assert "needs_clarification" in PLANNING_SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_planner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.command.planner'`

- [ ] **Step 3: Implement PlannerAgent**

Create `src/max/command/planner.py`:

```python
"""PlannerAgent — task decomposition, clarification, execution plan creation."""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from typing import Any

from max.agents.base import AgentConfig, AgentContext, BaseAgent
from max.command.models import ExecutionPlan, PlannedSubtask
from max.command.task_store import TaskStore
from max.config import Settings
from max.llm.client import LLMClient

logger = logging.getLogger(__name__)

PLANNING_SYSTEM_PROMPT = """You are the Planner for Max, an autonomous AI agent system.
Your job is to decompose a task into executable subtasks organized by phase.

Subtasks within the same phase can run in parallel. Phases execute sequentially.

Goal: {goal_anchor}
Priority: {priority}
Quality criteria: {quality_criteria}

Return ONLY valid JSON:
{{
  "subtasks": [
    {{
      "description": "Clear description of what this subtask does",
      "phase_number": 1,
      "tool_categories": [],
      "quality_criteria": {{}},
      "estimated_complexity": "low | moderate | high"
    }}
  ],
  "needs_clarification": false,
  "clarification_question": null,
  "clarification_options": [],
  "reasoning": "Explanation of your decomposition"
}}

Rules:
- Phase numbers start at 1
- Subtasks in the same phase have no dependencies on each other
- Each phase depends on all previous phases completing
- Be specific — each subtask should be independently executable
- If the goal is ambiguous, set needs_clarification=true and provide a question"""


class PlannerAgent(BaseAgent):
    """Decomposes tasks into phased execution plans."""

    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        bus: Any,
        db: Any,
        warm_memory: Any,
        settings: Settings,
        task_store: TaskStore,
    ) -> None:
        context = AgentContext(bus=bus, db=db, warm_memory=warm_memory)
        super().__init__(config=config, llm=llm, context=context)
        self._bus = bus
        self._db = db
        self._warm = warm_memory
        self._settings = settings
        self._task_store = task_store
        self._pending_clarifications: dict[uuid_mod.UUID, dict[str, Any]] = {}

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """BaseAgent abstract method — not used directly."""
        return {}

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to bus channels."""
        await self._bus.subscribe("tasks.plan", self.on_task_plan)
        await self._bus.subscribe("clarifications.response", self.on_clarification_response)
        await self._bus.subscribe("tasks.context_update", self.on_context_update)
        await self.on_start()
        logger.info("PlannerAgent started")

    async def stop(self) -> None:
        """Unsubscribe from bus channels."""
        await self._bus.unsubscribe("tasks.plan", self.on_task_plan)
        await self._bus.unsubscribe("clarifications.response", self.on_clarification_response)
        await self._bus.unsubscribe("tasks.context_update", self.on_context_update)
        await self.on_stop()
        logger.info("PlannerAgent stopped")

    # ── Bus handlers ────────────────────────────────────────────────────

    async def on_task_plan(self, channel: str, data: dict[str, Any]) -> None:
        """Decompose a task into an execution plan."""
        task_id = uuid_mod.UUID(data["task_id"])
        goal_anchor = data.get("goal_anchor", "")
        priority = data.get("priority", "normal")
        quality_criteria = data.get("quality_criteria", {})

        await self._decompose_and_publish(
            task_id, goal_anchor, priority, quality_criteria
        )

    async def on_clarification_response(self, channel: str, data: dict[str, Any]) -> None:
        """Resume planning after receiving user clarification."""
        task_id = uuid_mod.UUID(data["task_id"])
        answer = data.get("answer", "")

        pending = self._pending_clarifications.pop(task_id, None)
        if pending is None:
            logger.warning("Clarification response for unknown task %s", task_id)
            return

        # Incorporate the answer into the goal
        original_goal = pending.get("goal_anchor", "")
        enriched_goal = f"{original_goal}\nUser clarification: {answer}"

        await self._decompose_and_publish(
            task_id,
            enriched_goal,
            pending.get("priority", "normal"),
            pending.get("quality_criteria", {}),
        )

    async def on_context_update(self, channel: str, data: dict[str, Any]) -> None:
        """Handle additional context for a task being planned."""
        task_id = uuid_mod.UUID(data["task_id"])
        context_text = data.get("context_text", "")
        if task_id in self._pending_clarifications:
            self._pending_clarifications[task_id]["extra_context"] = context_text

    # ── Core planning logic ─────────────────────────────────────────────

    async def _decompose_and_publish(
        self,
        task_id: uuid_mod.UUID,
        goal_anchor: str,
        priority: str,
        quality_criteria: dict[str, Any],
    ) -> None:
        """LLM decomposition → persist subtasks → publish ExecutionPlan."""
        prompt = PLANNING_SYSTEM_PROMPT.format(
            goal_anchor=goal_anchor,
            priority=priority,
            quality_criteria=json.dumps(quality_criteria) if quality_criteria else "None",
        )

        self.reset()
        try:
            response = await self.think(
                messages=[{"role": "user", "content": f"Decompose this task: {goal_anchor}"}],
                system_prompt=prompt,
            )
            parsed = self._parse_plan_response(response.text)
        except Exception:
            logger.exception("Planner decomposition failed")
            parsed = {
                "subtasks": [{"description": goal_anchor, "phase_number": 1,
                              "tool_categories": [], "quality_criteria": {},
                              "estimated_complexity": "moderate"}],
                "needs_clarification": False,
                "reasoning": "Fallback: single-step execution",
            }

        # Handle clarification
        if parsed.get("needs_clarification"):
            self._pending_clarifications[task_id] = {
                "goal_anchor": goal_anchor,
                "priority": priority,
                "quality_criteria": quality_criteria,
            }
            await self._bus.publish("clarifications.new", {
                "id": str(uuid_mod.uuid4()),
                "task_id": str(task_id),
                "question": parsed.get("clarification_question", "Could you clarify?"),
                "options": parsed.get("clarification_options", []),
            })
            return

        # Cap subtasks at configured max
        raw_subtasks = parsed.get("subtasks", [])
        max_subtasks = self._settings.planner_max_subtasks
        capped_subtasks = raw_subtasks[:max_subtasks]

        # Persist subtasks to DB
        planned: list[PlannedSubtask] = []
        for st_data in capped_subtasks:
            ps = PlannedSubtask(
                description=st_data.get("description", ""),
                phase_number=st_data.get("phase_number", 1),
                tool_categories=st_data.get("tool_categories", []),
                quality_criteria=st_data.get("quality_criteria", {}),
                estimated_complexity=st_data.get("estimated_complexity", "moderate"),
            )
            await self._task_store.create_subtask(
                task_id=task_id,
                description=ps.description,
                phase_number=ps.phase_number,
                tool_categories=ps.tool_categories,
                quality_criteria=ps.quality_criteria,
                estimated_complexity=ps.estimated_complexity,
            )
            planned.append(ps)

        # Build and publish execution plan
        total_phases = max((p.phase_number for p in planned), default=1)
        plan = ExecutionPlan(
            task_id=task_id,
            goal_anchor=goal_anchor,
            subtasks=planned,
            total_phases=total_phases,
            reasoning=parsed.get("reasoning", ""),
        )
        await self._bus.publish("tasks.execute", plan.model_dump(mode="json"))

    @staticmethod
    def _parse_plan_response(text: str) -> dict[str, Any]:
        """Parse LLM JSON response for planning."""
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except (json.JSONDecodeError, ValueError):
                    continue
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {
                "subtasks": [],
                "needs_clarification": True,
                "clarification_question": "I couldn't understand the task. Could you rephrase?",
                "reasoning": "Failed to parse plan",
            }
```

- [ ] **Step 4: Run planner tests**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_planner.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest --tb=short -q`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/max/command/planner.py tests/test_planner.py
git commit -m "feat(command): add PlannerAgent with task decomposition and clarification"
```

---

### Task 7: Orchestrator Agent

**Files:**
- Create: `src/max/command/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing Orchestrator tests**

Create `tests/test_orchestrator.py`:

```python
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.command.orchestrator import OrchestratorAgent
from max.command.models import SubtaskResult, WorkerConfig
from max.agents.base import AgentConfig
from max.config import Settings
from max.llm.models import ModelType


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_orchestrator(bus, db, warm, settings, runner=None):
    config = AgentConfig(name="orchestrator", system_prompt="", model=ModelType.OPUS)
    llm = AsyncMock()
    task_store = AsyncMock()
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
        runner.run = AsyncMock(return_value=SubtaskResult(
            subtask_id=subtask_id, task_id=task_id,
            success=True, content="Done", confidence=0.9,
        ))

        orch = _make_orchestrator(bus, db, warm, settings, runner)
        orch._task_store.get_subtasks = AsyncMock(return_value=[
            {"id": subtask_id, "description": "Do work", "phase_number": 1,
             "tool_categories": [], "quality_criteria": {}, "status": "pending"},
        ])
        orch._task_store.update_subtask_result = AsyncMock()
        orch._task_store.update_subtask_status = AsyncMock()
        orch._task_store.create_result = AsyncMock(return_value=uuid.uuid4())

        plan_data = {
            "task_id": str(task_id),
            "goal_anchor": "Test task",
            "subtasks": [
                {"description": "Do work", "phase_number": 1,
                 "tool_categories": [], "quality_criteria": {},
                 "estimated_complexity": "moderate"},
            ],
            "total_phases": 1,
            "reasoning": "Simple task",
            "created_at": "2026-04-05T00:00:00Z",
        }
        await orch.on_execute("tasks.execute", plan_data)

        # Should publish tasks.complete
        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "tasks.complete" in channels

        complete_call = next(c for c in calls if c[0][0] == "tasks.complete")
        assert complete_call[0][1]["success"] is True

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
        runner.run = AsyncMock(side_effect=[
            SubtaskResult(subtask_id=s1_id, task_id=task_id, success=True, content="A", confidence=0.9),
            SubtaskResult(subtask_id=s2_id, task_id=task_id, success=True, content="B", confidence=0.8),
            SubtaskResult(subtask_id=s3_id, task_id=task_id, success=True, content="C", confidence=0.95),
        ])

        orch = _make_orchestrator(bus, db, warm, settings, runner)
        orch._task_store.get_subtasks = AsyncMock(return_value=[
            {"id": s1_id, "description": "Step A", "phase_number": 1,
             "tool_categories": [], "quality_criteria": {}, "status": "pending"},
            {"id": s2_id, "description": "Step B", "phase_number": 1,
             "tool_categories": [], "quality_criteria": {}, "status": "pending"},
            {"id": s3_id, "description": "Step C", "phase_number": 2,
             "tool_categories": [], "quality_criteria": {}, "status": "pending"},
        ])
        orch._task_store.update_subtask_result = AsyncMock()
        orch._task_store.update_subtask_status = AsyncMock()
        orch._task_store.create_result = AsyncMock(return_value=uuid.uuid4())

        plan_data = {
            "task_id": str(task_id),
            "goal_anchor": "Multi-phase task",
            "subtasks": [
                {"description": "Step A", "phase_number": 1, "tool_categories": [],
                 "quality_criteria": {}, "estimated_complexity": "low"},
                {"description": "Step B", "phase_number": 1, "tool_categories": [],
                 "quality_criteria": {}, "estimated_complexity": "low"},
                {"description": "Step C", "phase_number": 2, "tool_categories": [],
                 "quality_criteria": {}, "estimated_complexity": "moderate"},
            ],
            "total_phases": 2,
            "reasoning": "Two phases",
            "created_at": "2026-04-05T00:00:00Z",
        }
        await orch.on_execute("tasks.execute", plan_data)

        # 3 worker runs
        assert runner.run.call_count == 3

        calls = bus.publish.call_args_list
        channels = [c[0][0] for c in calls]
        assert "tasks.complete" in channels

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
        # Fail twice, succeed on third try (retry_count = 2)
        runner.run = AsyncMock(side_effect=[
            SubtaskResult(subtask_id=s_id, task_id=task_id, success=False, error="Temp error"),
            SubtaskResult(subtask_id=s_id, task_id=task_id, success=False, error="Temp error"),
            SubtaskResult(subtask_id=s_id, task_id=task_id, success=True, content="OK", confidence=0.7),
        ])

        orch = _make_orchestrator(bus, db, warm, settings, runner)
        orch._task_store.get_subtasks = AsyncMock(return_value=[
            {"id": s_id, "description": "Flaky task", "phase_number": 1,
             "tool_categories": [], "quality_criteria": {}, "status": "pending"},
        ])
        orch._task_store.update_subtask_result = AsyncMock()
        orch._task_store.update_subtask_status = AsyncMock()
        orch._task_store.create_result = AsyncMock(return_value=uuid.uuid4())

        plan_data = {
            "task_id": str(task_id),
            "goal_anchor": "Flaky task",
            "subtasks": [
                {"description": "Flaky task", "phase_number": 1,
                 "tool_categories": [], "quality_criteria": {},
                 "estimated_complexity": "moderate"},
            ],
            "total_phases": 1,
            "reasoning": "Single step",
            "created_at": "2026-04-05T00:00:00Z",
        }
        await orch.on_execute("tasks.execute", plan_data)

        # 3 runner calls: 2 failures + 1 success
        assert runner.run.call_count == 3

        calls = bus.publish.call_args_list
        complete = next(c for c in calls if c[0][0] == "tasks.complete")
        assert complete[0][1]["success"] is True

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
        runner.run = AsyncMock(return_value=SubtaskResult(
            subtask_id=s_id, task_id=task_id, success=False, error="Persistent error",
        ))

        orch = _make_orchestrator(bus, db, warm, settings, runner)
        orch._task_store.get_subtasks = AsyncMock(return_value=[
            {"id": s_id, "description": "Doomed task", "phase_number": 1,
             "tool_categories": [], "quality_criteria": {}, "status": "pending"},
        ])
        orch._task_store.update_subtask_result = AsyncMock()
        orch._task_store.update_subtask_status = AsyncMock()

        plan_data = {
            "task_id": str(task_id),
            "goal_anchor": "Doomed task",
            "subtasks": [
                {"description": "Doomed task", "phase_number": 1,
                 "tool_categories": [], "quality_criteria": {},
                 "estimated_complexity": "moderate"},
            ],
            "total_phases": 1,
            "reasoning": "Will fail",
            "created_at": "2026-04-05T00:00:00Z",
        }
        await orch.on_execute("tasks.execute", plan_data)

        # 1 original + 2 retries = 3
        assert runner.run.call_count == 3

        calls = bus.publish.call_args_list
        complete = next(c for c in calls if c[0][0] == "tasks.complete")
        assert complete[0][1]["success"] is False


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
        orch._task_store.get_subtasks = AsyncMock(return_value=[
            {"id": uuid.uuid4(), "status": "in_progress"},
        ])
        orch._task_store.update_subtask_status = AsyncMock()

        await orch.on_cancel("tasks.cancel", {"task_id": str(task_id)})
        assert task_id in orch._cancelled_tasks


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'max.command.orchestrator'`

- [ ] **Step 3: Implement OrchestratorAgent**

Create `src/max/command/orchestrator.py`:

```python
"""OrchestratorAgent — phase execution, worker lifecycle, result assembly."""

from __future__ import annotations

import asyncio
import logging
import uuid as uuid_mod
from collections import defaultdict
from typing import Any

from max.agents.base import AgentConfig, AgentContext, BaseAgent
from max.command.models import ExecutionPlan, PlannedSubtask, SubtaskResult, WorkerConfig
from max.command.runner import AgentRunner
from max.command.task_store import TaskStore
from max.config import Settings
from max.llm.client import LLMClient
from max.models.tasks import TaskStatus

logger = logging.getLogger(__name__)

WORKER_BASE_PROMPT = """You are a worker agent for Max.

Your subtask: {description}

Context from previous phases:
{prior_results}

Produce the best possible result for this subtask.

Return ONLY valid JSON:
{{
  "content": "Your complete work product",
  "confidence": 0.0 to 1.0,
  "reasoning": "How you approached this"
}}"""


class OrchestratorAgent(BaseAgent):
    """Manages worker agent lifecycle and phase-by-phase execution."""

    def __init__(
        self,
        config: AgentConfig,
        llm: LLMClient,
        bus: Any,
        db: Any,
        warm_memory: Any,
        settings: Settings,
        task_store: TaskStore,
        runner: AgentRunner,
    ) -> None:
        context = AgentContext(bus=bus, db=db, warm_memory=warm_memory)
        super().__init__(config=config, llm=llm, context=context)
        self._bus = bus
        self._db = db
        self._warm = warm_memory
        self._settings = settings
        self._task_store = task_store
        self._runner = runner
        self._cancelled_tasks: set[uuid_mod.UUID] = set()

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """BaseAgent abstract method — not used directly."""
        return {}

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to bus channels."""
        await self._bus.subscribe("tasks.execute", self.on_execute)
        await self._bus.subscribe("tasks.cancel", self.on_cancel)
        await self._bus.subscribe("tasks.context_update", self.on_context_update)
        await self.on_start()
        logger.info("OrchestratorAgent started")

    async def stop(self) -> None:
        """Unsubscribe from bus channels."""
        await self._bus.unsubscribe("tasks.execute", self.on_execute)
        await self._bus.unsubscribe("tasks.cancel", self.on_cancel)
        await self._bus.unsubscribe("tasks.context_update", self.on_context_update)
        await self.on_stop()
        logger.info("OrchestratorAgent stopped")

    # ── Bus handlers ────────────────────────────────────────────────────

    async def on_execute(self, channel: str, data: dict[str, Any]) -> None:
        """Execute a plan phase by phase."""
        plan = ExecutionPlan.model_validate(data)
        task_id = plan.task_id

        # Get subtasks from DB (they have real IDs)
        db_subtasks = await self._task_store.get_subtasks(task_id)

        # Group DB subtasks by phase
        phases: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for st in db_subtasks:
            phases[st["phase_number"]].append(st)

        prior_results: list[SubtaskResult] = []
        all_succeeded = True
        total_subtasks = len(db_subtasks)
        completed_count = 0

        for phase_num in sorted(phases.keys()):
            if task_id in self._cancelled_tasks:
                all_succeeded = False
                break

            phase_subtasks = phases[phase_num]

            # Run all subtasks in this phase concurrently
            results = await asyncio.gather(
                *(
                    self._execute_subtask(st, task_id, prior_results)
                    for st in phase_subtasks
                ),
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, Exception):
                    logger.error("Subtask raised exception: %s", result)
                    all_succeeded = False
                    continue

                if result.success:
                    prior_results.append(result)
                    completed_count += 1
                    await self._task_store.update_subtask_result(
                        result.subtask_id,
                        {"content": result.content, "confidence": result.confidence,
                         "reasoning": result.reasoning},
                    )
                else:
                    all_succeeded = False
                    await self._task_store.update_subtask_status(
                        result.subtask_id, TaskStatus.FAILED
                    )

            # Publish progress
            progress = completed_count / total_subtasks if total_subtasks > 0 else 0.0
            await self._bus.publish("status_updates.new", {
                "id": str(uuid_mod.uuid4()),
                "task_id": str(task_id),
                "message": f"Phase {phase_num} complete ({completed_count}/{total_subtasks} subtasks)",
                "progress": progress,
            })

            if not all_succeeded:
                break

        # Assemble and publish result
        if all_succeeded and prior_results:
            combined_content = "\n\n".join(r.content for r in prior_results if r.content)
            avg_confidence = sum(r.confidence for r in prior_results) / len(prior_results)
            await self._task_store.create_result(
                task_id=task_id,
                content=combined_content,
                confidence=avg_confidence,
            )
            await self._bus.publish("tasks.complete", {
                "task_id": str(task_id),
                "success": True,
                "result_content": combined_content,
                "confidence": avg_confidence,
            })
        else:
            error_msgs = [
                r.error for r in prior_results if not r.success and r.error
            ] if prior_results else ["All subtasks failed"]
            await self._bus.publish("tasks.complete", {
                "task_id": str(task_id),
                "success": False,
                "error": "; ".join(error_msgs) if error_msgs else "Execution failed",
            })

    async def on_cancel(self, channel: str, data: dict[str, Any]) -> None:
        """Mark a task as cancelled to abort execution."""
        task_id = uuid_mod.UUID(data["task_id"])
        self._cancelled_tasks.add(task_id)
        logger.info("Task %s marked for cancellation", task_id)

        # Mark in-progress subtasks as failed
        subtasks = await self._task_store.get_subtasks(task_id)
        for st in subtasks:
            if st["status"] in ("pending", "in_progress"):
                await self._task_store.update_subtask_status(st["id"], TaskStatus.FAILED)

    async def on_context_update(self, channel: str, data: dict[str, Any]) -> None:
        """Receive additional context — stored for future worker reference."""
        logger.info("Context update for task %s", data.get("task_id"))

    # ── Worker execution ────────────────────────────────────────────────

    async def _execute_subtask(
        self,
        subtask: dict[str, Any],
        task_id: uuid_mod.UUID,
        prior_results: list[SubtaskResult],
    ) -> SubtaskResult:
        """Execute a single subtask with retries."""
        subtask_id = subtask["id"]
        description = subtask["description"]
        quality_criteria = subtask.get("quality_criteria", {})
        max_retries = self._settings.worker_max_retries

        await self._task_store.update_subtask_status(subtask_id, TaskStatus.IN_PROGRESS)

        # Build context from prior results
        prior_summary = "\n".join(
            f"- {r.content[:200]}" for r in prior_results if r.content
        ) or "None (first phase)"

        system_prompt = WORKER_BASE_PROMPT.format(
            description=description,
            prior_results=prior_summary,
        )

        config = WorkerConfig(
            subtask_id=subtask_id,
            task_id=task_id,
            system_prompt=system_prompt,
            quality_criteria=quality_criteria if isinstance(quality_criteria, dict) else {},
        )

        context = AgentContext(
            bus=self._bus, db=self._db, warm_memory=self._warm
        )

        last_result: SubtaskResult | None = None
        for attempt in range(1 + max_retries):
            if task_id in self._cancelled_tasks:
                return SubtaskResult(
                    subtask_id=subtask_id, task_id=task_id,
                    success=False, error="Task cancelled",
                )

            try:
                result = await asyncio.wait_for(
                    self._runner.run(config, context),
                    timeout=self._settings.worker_timeout_seconds,
                )
            except asyncio.TimeoutError:
                result = SubtaskResult(
                    subtask_id=subtask_id, task_id=task_id,
                    success=False, error=f"Worker timed out after {self._settings.worker_timeout_seconds}s",
                )

            if result.success:
                return result
            last_result = result
            if attempt < max_retries:
                logger.warning(
                    "Subtask %s failed (attempt %d/%d): %s",
                    subtask_id, attempt + 1, 1 + max_retries, result.error,
                )

        return last_result or SubtaskResult(
            subtask_id=subtask_id, task_id=task_id,
            success=False, error="All retries exhausted",
        )
```

- [ ] **Step 4: Run orchestrator tests**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_orchestrator.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest --tb=short -q`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/max/command/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(command): add OrchestratorAgent with phase execution and retry logic"
```

---

### Task 8: Package Exports

**Files:**
- Modify: `src/max/command/__init__.py`

- [ ] **Step 1: Update package exports**

Replace `src/max/command/__init__.py` with the full export list:

```python
"""Phase 4: Command Chain — Coordinator, Planner, Orchestrator pipeline."""

from max.command.coordinator import CoordinatorAgent
from max.command.models import (
    CoordinatorAction,
    CoordinatorActionType,
    ExecutionPlan,
    PlannedSubtask,
    SubtaskResult,
    WorkerConfig,
)
from max.command.orchestrator import OrchestratorAgent
from max.command.planner import PlannerAgent
from max.command.runner import AgentRunner, InProcessRunner
from max.command.task_store import TaskStore
from max.command.worker import WorkerAgent

__all__ = [
    "AgentRunner",
    "CoordinatorAction",
    "CoordinatorActionType",
    "CoordinatorAgent",
    "ExecutionPlan",
    "InProcessRunner",
    "OrchestratorAgent",
    "PlannedSubtask",
    "PlannerAgent",
    "SubtaskResult",
    "TaskStore",
    "WorkerAgent",
    "WorkerConfig",
]
```

- [ ] **Step 2: Verify imports work**

Run: `cd /home/venu/Desktop/everactive && uv run python -c "from max.command import CoordinatorAgent, PlannerAgent, OrchestratorAgent, WorkerAgent, InProcessRunner, TaskStore; print('OK')""`
Expected: `OK`

- [ ] **Step 3: Run full test suite**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest --tb=short -q`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add src/max/command/__init__.py
git commit -m "feat(command): add package exports for command chain"
```

---

### Task 9: End-to-End Integration Test

**Files:**
- Create: `tests/test_command_integration.py`

- [ ] **Step 1: Write the integration test**

Create `tests/test_command_integration.py`:

```python
"""End-to-end integration test for the Command Chain pipeline.

Tests the full flow: intent → Coordinator → Planner → Orchestrator → Workers → result.
All LLM calls are mocked. Bus, DB, and state are real or near-real.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.agents.base import AgentConfig, AgentContext
from max.command.coordinator import CoordinatorAgent
from max.command.models import SubtaskResult
from max.command.orchestrator import OrchestratorAgent
from max.command.planner import PlannerAgent
from max.command.runner import InProcessRunner
from max.command.task_store import TaskStore
from max.config import Settings
from max.llm.models import LLMResponse, ModelType


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_llm_response(data: dict | str) -> LLMResponse:
    text = json.dumps(data) if isinstance(data, dict) else data
    return LLMResponse(
        text=text,
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_intent_to_result_happy_path(self, monkeypatch):
        """Full pipeline: intent → coordinator → planner → orchestrator → result."""
        settings = _make_settings(monkeypatch)

        # Track all bus publications
        publications: list[tuple[str, dict]] = []

        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()

        async def mock_publish(channel, data):
            publications.append((channel, data))

        bus.publish = AsyncMock(side_effect=mock_publish)

        db = AsyncMock()
        warm = AsyncMock()

        # Set up coordinator LLM — classifies as create_task
        coordinator_llm = AsyncMock()
        coordinator_llm.complete = AsyncMock(return_value=_make_llm_response({
            "action": "create_task",
            "goal_anchor": "Summarize Python 3.13 features",
            "priority": "normal",
            "quality_criteria": {},
            "reasoning": "New research request",
        }))

        # Set up planner LLM — decomposes into 2 subtasks
        planner_llm = AsyncMock()
        planner_llm.complete = AsyncMock(return_value=_make_llm_response({
            "subtasks": [
                {"description": "Research Python 3.13 features", "phase_number": 1,
                 "tool_categories": [], "quality_criteria": {}, "estimated_complexity": "low"},
                {"description": "Write summary", "phase_number": 2,
                 "tool_categories": [], "quality_criteria": {}, "estimated_complexity": "moderate"},
            ],
            "needs_clarification": False,
            "reasoning": "Research then summarize",
        }))

        # Set up worker LLM — returns results
        worker_llm = AsyncMock()
        worker_call_count = 0

        async def worker_complete(**kwargs):
            nonlocal worker_call_count
            worker_call_count += 1
            if worker_call_count == 1:
                return _make_llm_response({
                    "content": "Python 3.13 has better error messages and JIT.",
                    "confidence": 0.85,
                    "reasoning": "Based on PEPs",
                })
            return _make_llm_response({
                "content": "Summary: Python 3.13 brings improved error messages and experimental JIT compiler.",
                "confidence": 0.9,
                "reasoning": "Synthesized from research",
            })

        worker_llm.complete = AsyncMock(side_effect=worker_complete)

        # Build components
        task_store = AsyncMock()
        intent_id = uuid.uuid4()
        task_id = uuid.uuid4()
        s1_id, s2_id = uuid.uuid4(), uuid.uuid4()

        task_store.create_task = AsyncMock(return_value={
            "id": task_id, "goal_anchor": "Summarize Python 3.13 features",
            "status": "pending", "priority": "normal",
        })
        task_store.update_task_status = AsyncMock()
        task_store.get_task = AsyncMock(return_value={
            "id": task_id, "goal_anchor": "Summarize Python 3.13 features",
        })
        task_store.create_subtask = AsyncMock(side_effect=[
            {"id": s1_id, "description": "Research", "phase_number": 1, "status": "pending"},
            {"id": s2_id, "description": "Write summary", "phase_number": 2, "status": "pending"},
        ])
        task_store.get_subtasks = AsyncMock(return_value=[
            {"id": s1_id, "description": "Research Python 3.13 features",
             "phase_number": 1, "tool_categories": [], "quality_criteria": {}, "status": "pending"},
            {"id": s2_id, "description": "Write summary",
             "phase_number": 2, "tool_categories": [], "quality_criteria": {}, "status": "pending"},
        ])
        task_store.update_subtask_result = AsyncMock()
        task_store.update_subtask_status = AsyncMock()
        task_store.create_result = AsyncMock(return_value=uuid.uuid4())

        state_mgr = AsyncMock()
        state_mgr.load = AsyncMock(return_value=MagicMock(
            active_tasks=[], task_queue=[], model_dump=MagicMock(return_value={}),
        ))
        state_mgr.save = AsyncMock()

        runner = InProcessRunner(llm=worker_llm)

        coordinator = CoordinatorAgent(
            config=AgentConfig(name="coordinator", system_prompt="", model=ModelType.OPUS),
            llm=coordinator_llm, bus=bus, db=db, warm_memory=warm,
            settings=settings, state_manager=state_mgr, task_store=task_store,
        )

        planner = PlannerAgent(
            config=AgentConfig(name="planner", system_prompt="", model=ModelType.OPUS),
            llm=planner_llm, bus=bus, db=db, warm_memory=warm,
            settings=settings, task_store=task_store,
        )

        orchestrator = OrchestratorAgent(
            config=AgentConfig(name="orchestrator", system_prompt="", model=ModelType.OPUS),
            llm=AsyncMock(), bus=bus, db=db, warm_memory=warm,
            settings=settings, task_store=task_store, runner=runner,
        )

        # Run the pipeline manually (in production, bus routes between agents)
        # Step 1: Coordinator receives intent
        intent_data = {
            "id": str(intent_id),
            "user_message": "Research and summarize Python 3.13 features",
            "source_platform": "telegram",
            "goal_anchor": "Summarize Python 3.13 features",
            "priority": "normal",
        }
        await coordinator.on_intent("intents.new", intent_data)

        # Step 2: Find the tasks.plan publication and feed to planner
        plan_pub = next(
            (ch, d) for ch, d in publications if ch == "tasks.plan"
        )
        await planner.on_task_plan("tasks.plan", plan_pub[1])

        # Step 3: Find the tasks.execute publication and feed to orchestrator
        exec_pub = next(
            (ch, d) for ch, d in publications if ch == "tasks.execute"
        )
        await orchestrator.on_execute("tasks.execute", exec_pub[1])

        # Step 4: Find the tasks.complete publication and feed back to coordinator
        complete_pub = next(
            (ch, d) for ch, d in publications if ch == "tasks.complete"
        )
        await coordinator.on_task_complete("tasks.complete", complete_pub[1])

        # Verify the full flow produced a result
        result_pubs = [(ch, d) for ch, d in publications if ch == "results.new"]
        assert len(result_pubs) == 1
        result_data = result_pubs[0][1]
        assert "Python 3.13" in result_data["content"]
        assert result_data["confidence"] > 0.0

        # Verify status updates were published
        status_pubs = [(ch, d) for ch, d in publications if ch == "status_updates.new"]
        assert len(status_pubs) >= 2  # At least planning + phase progress


class TestClarificationPipeline:
    @pytest.mark.asyncio
    async def test_clarification_flow(self, monkeypatch):
        """Test: ambiguous intent → clarification → resume → result."""
        settings = _make_settings(monkeypatch)
        publications: list[tuple[str, dict]] = []
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()

        async def mock_publish(channel, data):
            publications.append((channel, data))

        bus.publish = AsyncMock(side_effect=mock_publish)
        db = AsyncMock()
        warm = AsyncMock()

        # Planner LLM: first asks for clarification, then decomposes
        call_count = 0
        planner_llm = AsyncMock()

        async def planner_complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response({
                    "subtasks": [],
                    "needs_clarification": True,
                    "clarification_question": "Which app?",
                    "clarification_options": ["App A", "App B"],
                    "reasoning": "Ambiguous",
                })
            return _make_llm_response({
                "subtasks": [
                    {"description": "Deploy App A", "phase_number": 1,
                     "tool_categories": [], "quality_criteria": {},
                     "estimated_complexity": "moderate"},
                ],
                "needs_clarification": False,
                "reasoning": "Clear after clarification",
            })

        planner_llm.complete = AsyncMock(side_effect=planner_complete)

        task_store = AsyncMock()
        task_id = uuid.uuid4()
        task_store.create_subtask = AsyncMock(return_value={
            "id": uuid.uuid4(), "description": "Deploy App A",
            "phase_number": 1, "status": "pending",
        })

        planner = PlannerAgent(
            config=AgentConfig(name="planner", system_prompt="", model=ModelType.OPUS),
            llm=planner_llm, bus=bus, db=db, warm_memory=warm,
            settings=settings, task_store=task_store,
        )

        # Step 1: Plan request triggers clarification
        await planner.on_task_plan("tasks.plan", {
            "task_id": str(task_id),
            "goal_anchor": "Deploy the thing",
            "priority": "normal",
            "quality_criteria": {},
        })

        clarification_pubs = [(ch, d) for ch, d in publications if ch == "clarifications.new"]
        assert len(clarification_pubs) == 1
        assert "Which app?" in clarification_pubs[0][1]["question"]

        # Step 2: User answers, resume planning
        await planner.on_clarification_response("clarifications.response", {
            "task_id": str(task_id),
            "answer": "App A",
        })

        exec_pubs = [(ch, d) for ch, d in publications if ch == "tasks.execute"]
        assert len(exec_pubs) == 1
        assert "Deploy App A" in json.dumps(exec_pubs[0][1])
```

- [ ] **Step 2: Run integration tests**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest tests/test_command_integration.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest --tb=short -q`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_command_integration.py
git commit -m "test(command): add end-to-end command chain integration tests"
```

---

### Task 10: Lint, Format, Final Test Run

**Files:**
- All `src/max/command/*.py` and `tests/test_command*.py`, `tests/test_task_store.py`, `tests/test_worker.py`, `tests/test_runner.py`, `tests/test_orchestrator.py`

- [ ] **Step 1: Run ruff format**

Run: `cd /home/venu/Desktop/everactive && uv run ruff format src/max/command/ tests/test_command*.py tests/test_task_store.py tests/test_worker.py tests/test_runner.py tests/test_orchestrator.py`

- [ ] **Step 2: Run ruff check and fix**

Run: `cd /home/venu/Desktop/everactive && uv run ruff check --fix src/max/command/ tests/test_command*.py tests/test_task_store.py tests/test_worker.py tests/test_runner.py tests/test_orchestrator.py`

- [ ] **Step 3: Run full test suite**

Run: `cd /home/venu/Desktop/everactive && uv run python -m pytest --tb=short -q`
Expected: All tests pass (280+ total)

- [ ] **Step 4: Commit if any changes**

```bash
git add -u
git commit -m "style: format and lint Phase 4 command chain code"
```

---

## Self-Review

### Spec Coverage Check

| Spec Section | Task(s) |
|-------------|---------|
| 2.1 Coordinator | Task 5 |
| 2.2 Planner | Task 6 |
| 2.3 Orchestrator | Task 7 |
| 2.4 WorkerAgent | Task 4 |
| 2.5 AgentRunner | Task 4 |
| 2.6 TaskStore | Task 3 |
| 3 Data Models | Task 2 |
| 4 Bus Channel Topology | Tasks 5, 6, 7 (subscribe/publish in each) |
| 5 Happy Path | Task 9 (integration test) |
| 6 Clarification Path | Task 9 (ClarificationPipeline test) |
| 7 Cancellation Path | Task 7 (cancellation test) |
| 8 Error Handling | Task 7 (retry tests) |
| 9 Configuration | Task 1 |
| 10 Database Changes | Task 1 |
| 11 File Structure | All tasks |
| 12 Testing Strategy | All test files |
| 8 Package Exports | Task 8 |

All spec sections covered. No gaps.

### Placeholder Scan
No TBD, TODO, or vague steps found. All code blocks are complete.

### Type Consistency
- `CoordinatorAction` / `CoordinatorActionType` — consistent across Tasks 2, 5
- `ExecutionPlan` / `PlannedSubtask` — consistent across Tasks 2, 6, 7
- `WorkerConfig` / `SubtaskResult` — consistent across Tasks 2, 4, 7
- `TaskStore` methods — signatures match between Task 3 definition and usage in Tasks 5, 6, 7
- `AgentRunner.run(config, context)` — consistent between Task 4 definition and Task 7 usage

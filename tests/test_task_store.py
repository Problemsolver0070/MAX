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
        intent_id,
        "Test message",
        "telegram",
        "Test goal",
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
        intent_id,
        "Get test",
        "telegram",
        "Get goal",
    )
    created = await store.create_task(
        intent_id=intent_id,
        goal_anchor="Get goal",
        priority="high",
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
            intent_id,
            f"Msg {i}",
            "telegram",
            f"Goal {i}",
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
        intent_id,
        "Status test",
        "telegram",
        "Status goal",
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
        intent_id,
        "Complete test",
        "telegram",
        "Complete goal",
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
        intent_id,
        "Sub test",
        "telegram",
        "Sub goal",
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
        intent_id,
        "Multi sub",
        "telegram",
        "Multi goal",
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
        intent_id,
        "Result test",
        "telegram",
        "Result goal",
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
        intent_id,
        "Status sub",
        "telegram",
        "Status sub goal",
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
        intent_id,
        "Result create",
        "telegram",
        "Result create goal",
    )
    task = await store.create_task(intent_id=intent_id, goal_anchor="Result create goal")
    result_id = await store.create_result(
        task_id=task["id"],
        content="Final answer",
        confidence=0.9,
    )
    assert result_id is not None
    row = await db.fetchone("SELECT * FROM results WHERE id = $1", result_id)
    assert row["content"] == "Final answer"

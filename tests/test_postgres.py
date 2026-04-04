import uuid

import pytest

from max.db.postgres import Database


@pytest.fixture
async def db():
    database = Database(dsn="postgresql://max:max_dev_password@localhost:5432/max")
    await database.connect()
    # Clean test data
    await database.execute("DELETE FROM audit_reports")
    await database.execute("DELETE FROM subtasks")
    await database.execute("DELETE FROM tasks")
    yield database
    await database.execute("DELETE FROM audit_reports")
    await database.execute("DELETE FROM subtasks")
    await database.execute("DELETE FROM tasks")
    await database.close()


@pytest.mark.asyncio
async def test_connect_and_ping(db):
    row = await db.fetchone("SELECT 1 AS val")
    assert row["val"] == 1


@pytest.mark.asyncio
async def test_insert_and_fetch_task(db):
    task_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id, status) VALUES ($1, $2, $3, $4)",
        task_id,
        "Test goal",
        intent_id,
        "pending",
    )
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)
    assert row["goal_anchor"] == "Test goal"
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_fetchall(db):
    for i in range(3):
        await db.execute(
            "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
            uuid.uuid4(),
            f"Goal {i}",
            uuid.uuid4(),
        )
    rows = await db.fetchall("SELECT * FROM tasks ORDER BY created_at")
    assert len(rows) >= 3


@pytest.mark.asyncio
async def test_transaction_commit(db):
    task_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    async with db.transaction() as conn:
        await conn.execute(
            "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
            task_id,
            "Transactional goal",
            intent_id,
        )
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)
    assert row is not None
    assert row["goal_anchor"] == "Transactional goal"


@pytest.mark.asyncio
async def test_transaction_rollback(db):
    task_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    with pytest.raises(ValueError, match="Intentional rollback"):
        async with db.transaction() as conn:
            await conn.execute(
                "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
                task_id,
                "Should not persist",
                intent_id,
            )
            raise ValueError("Intentional rollback")
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)
    assert row is None

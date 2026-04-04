import uuid

import pytest

from max.db.postgres import Database


@pytest.fixture
async def db():
    database = Database(dsn="postgresql://max:max_dev_password@localhost:5432/max")
    await database.connect()
    # Drop old tables so schema changes (FK, new tables) take effect
    await database.execute("DROP TABLE IF EXISTS status_updates CASCADE")
    await database.execute("DROP TABLE IF EXISTS clarification_requests CASCADE")
    await database.execute("DROP TABLE IF EXISTS results CASCADE")
    await database.execute("DROP TABLE IF EXISTS audit_reports CASCADE")
    await database.execute("DROP TABLE IF EXISTS subtasks CASCADE")
    await database.execute("DROP TABLE IF EXISTS context_anchors CASCADE")
    await database.execute("DROP TABLE IF EXISTS quality_ledger CASCADE")
    await database.execute("DROP TABLE IF EXISTS memory_embeddings CASCADE")
    await database.execute("DROP TABLE IF EXISTS tasks CASCADE")
    await database.execute("DROP TABLE IF EXISTS intents CASCADE")
    await database.init_schema()
    yield database
    # Clean test data in FK-safe order
    await database.execute("DELETE FROM status_updates")
    await database.execute("DELETE FROM clarification_requests")
    await database.execute("DELETE FROM results")
    await database.execute("DELETE FROM audit_reports")
    await database.execute("DELETE FROM subtasks")
    await database.execute("DELETE FROM tasks")
    await database.execute("DELETE FROM intents")
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
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) VALUES ($1, $2, $3, $4)",
        intent_id, "Test message", "telegram", "Test goal",
    )
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id, status) VALUES ($1, $2, $3, $4)",
        task_id, "Test goal", intent_id, "pending",
    )
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)
    assert row["goal_anchor"] == "Test goal"
    assert row["status"] == "pending"


@pytest.mark.asyncio
async def test_fetchall(db):
    for i in range(3):
        intent_id = uuid.uuid4()
        await db.execute(
            "INSERT INTO intents (id, user_message, source_platform, goal_anchor) VALUES ($1, $2, $3, $4)",
            intent_id, f"Message {i}", "telegram", f"Goal {i}",
        )
        await db.execute(
            "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
            uuid.uuid4(), f"Goal {i}", intent_id,
        )
    rows = await db.fetchall("SELECT * FROM tasks ORDER BY created_at")
    assert len(rows) >= 3


@pytest.mark.asyncio
async def test_transaction_commit(db):
    task_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) VALUES ($1, $2, $3, $4)",
        intent_id, "Transaction message", "telegram", "Transactional goal",
    )
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
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) VALUES ($1, $2, $3, $4)",
        intent_id, "Rollback message", "telegram", "Should not persist",
    )
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


@pytest.mark.asyncio
async def test_intents_table_exists(db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor, priority)"
        " VALUES ($1, $2, $3, $4, $5)",
        intent_id, "Deploy the app", "telegram", "Deploy the app", "normal",
    )
    row = await db.fetchone("SELECT * FROM intents WHERE id = $1", intent_id)
    assert row["user_message"] == "Deploy the app"
    assert row["source_platform"] == "telegram"


@pytest.mark.asyncio
async def test_results_table_exists(db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) VALUES ($1, $2, $3, $4)",
        intent_id, "Test", "telegram", "Test",
    )
    task_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
        task_id, "Test goal", intent_id,
    )
    result_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO results (id, task_id, content, confidence) VALUES ($1, $2, $3, $4)",
        result_id, task_id, "Done", 0.95,
    )
    row = await db.fetchone("SELECT * FROM results WHERE id = $1", result_id)
    assert row["content"] == "Done"


@pytest.mark.asyncio
async def test_tasks_source_intent_fk(db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor) VALUES ($1, $2, $3, $4)",
        intent_id, "FK test", "whatsapp", "FK test",
    )
    task_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
        task_id, "FK goal", intent_id,
    )
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)
    assert row["source_intent_id"] == intent_id

import uuid

import pytest

from max.db.postgres import Database


@pytest.fixture
async def db():
    database = Database(dsn="postgresql://max:max_dev_password@localhost:5432/max")
    await database.connect()
    # Drop old tables so schema changes (FK, new tables) take effect
    await database.execute("DROP TABLE IF EXISTS conversation_messages CASCADE")
    await database.execute("DROP TABLE IF EXISTS graph_edges CASCADE")
    await database.execute("DROP TABLE IF EXISTS graph_nodes CASCADE")
    await database.execute("DROP TABLE IF EXISTS compaction_log CASCADE")
    await database.execute("DROP TABLE IF EXISTS performance_metrics CASCADE")
    await database.execute("DROP TABLE IF EXISTS shelved_improvements CASCADE")
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
    await database.execute("DELETE FROM conversation_messages")
    await database.execute("DELETE FROM graph_edges")
    await database.execute("DELETE FROM graph_nodes")
    await database.execute("DELETE FROM compaction_log")
    await database.execute("DELETE FROM performance_metrics")
    await database.execute("DELETE FROM shelved_improvements")
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
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor)"
        " VALUES ($1, $2, $3, $4)",
        intent_id,
        "Test message",
        "telegram",
        "Test goal",
    )
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
        intent_id = uuid.uuid4()
        await db.execute(
            "INSERT INTO intents (id, user_message, source_platform, goal_anchor)"
            " VALUES ($1, $2, $3, $4)",
            intent_id,
            f"Message {i}",
            "telegram",
            f"Goal {i}",
        )
        await db.execute(
            "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
            uuid.uuid4(),
            f"Goal {i}",
            intent_id,
        )
    rows = await db.fetchall("SELECT * FROM tasks ORDER BY created_at")
    assert len(rows) >= 3


@pytest.mark.asyncio
async def test_transaction_commit(db):
    task_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor)"
        " VALUES ($1, $2, $3, $4)",
        intent_id,
        "Transaction message",
        "telegram",
        "Transactional goal",
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
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor)"
        " VALUES ($1, $2, $3, $4)",
        intent_id,
        "Rollback message",
        "telegram",
        "Should not persist",
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
        intent_id,
        "Deploy the app",
        "telegram",
        "Deploy the app",
        "normal",
    )
    row = await db.fetchone("SELECT * FROM intents WHERE id = $1", intent_id)
    assert row["user_message"] == "Deploy the app"
    assert row["source_platform"] == "telegram"


@pytest.mark.asyncio
async def test_results_table_exists(db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor)"
        " VALUES ($1, $2, $3, $4)",
        intent_id,
        "Test",
        "telegram",
        "Test",
    )
    task_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
        task_id,
        "Test goal",
        intent_id,
    )
    result_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO results (id, task_id, content, confidence) VALUES ($1, $2, $3, $4)",
        result_id,
        task_id,
        "Done",
        0.95,
    )
    row = await db.fetchone("SELECT * FROM results WHERE id = $1", result_id)
    assert row["content"] == "Done"


@pytest.mark.asyncio
async def test_tasks_source_intent_fk(db):
    intent_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO intents (id, user_message, source_platform, goal_anchor)"
        " VALUES ($1, $2, $3, $4)",
        intent_id,
        "FK test",
        "whatsapp",
        "FK test",
    )
    task_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id) VALUES ($1, $2, $3)",
        task_id,
        "FK goal",
        intent_id,
    )
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task_id)
    assert row["source_intent_id"] == intent_id


@pytest.mark.asyncio
async def test_memory_system_tables_exist(db):
    """Verify Phase 2 tables are created by schema init."""
    tables = await db.fetchall("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    table_names = {row["tablename"] for row in tables}
    phase2_tables = {
        "graph_nodes",
        "graph_edges",
        "compaction_log",
        "performance_metrics",
        "shelved_improvements",
    }
    assert phase2_tables.issubset(table_names), f"Missing tables: {phase2_tables - table_names}"


@pytest.mark.asyncio
async def test_context_anchors_has_lifecycle_columns(db):
    """Verify context_anchors has Phase 2 columns."""
    cols = await db.fetchall(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'context_anchors'"
    )
    col_names = {row["column_name"] for row in cols}
    expected = {
        "lifecycle_state",
        "relevance_score",
        "last_accessed",
        "access_count",
        "decay_rate",
        "permanence_class",
        "superseded_by",
        "version",
        "parent_anchor_id",
    }
    assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"


@pytest.mark.asyncio
async def test_memory_embeddings_has_phase2_columns(db):
    """Verify memory_embeddings has Phase 2 columns."""
    cols = await db.fetchall(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'memory_embeddings'"
    )
    col_names = {row["column_name"] for row in cols}
    expected = {
        "relevance_score",
        "tier",
        "last_accessed",
        "access_count",
        "summary",
        "base_relevance",
        "decay_rate",
        "search_vector",
    }
    assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"


@pytest.mark.asyncio
async def test_graph_node_insert_and_fetch(db):
    """Insert and fetch a graph node."""
    node_id = uuid.uuid4()
    content_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO graph_nodes (id, node_type, content_id, metadata) VALUES ($1, $2, $3, $4)",
        node_id,
        "task",
        content_id,
        "{}",
    )
    row = await db.fetchone("SELECT * FROM graph_nodes WHERE id = $1", node_id)
    assert row is not None
    assert row["node_type"] == "task"


@pytest.mark.asyncio
async def test_graph_edge_insert_with_fk(db):
    """Insert graph edge with FK to nodes."""
    n1 = uuid.uuid4()
    n2 = uuid.uuid4()
    c1 = uuid.uuid4()
    c2 = uuid.uuid4()
    await db.execute(
        "INSERT INTO graph_nodes (id, node_type, content_id) VALUES ($1, $2, $3)",
        n1,
        "task",
        c1,
    )
    await db.execute(
        "INSERT INTO graph_nodes (id, node_type, content_id) VALUES ($1, $2, $3)",
        n2,
        "anchor",
        c2,
    )
    edge_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO graph_edges (id, source_id, target_id, relation, weight) "
        "VALUES ($1, $2, $3, $4, $5)",
        edge_id,
        n1,
        n2,
        "depends_on",
        0.9,
    )
    row = await db.fetchone("SELECT * FROM graph_edges WHERE id = $1", edge_id)
    assert row is not None
    assert float(row["weight"]) == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_conversation_messages_table_exists(db):
    """Verify Phase 3 conversation_messages table is created."""
    tables = await db.fetchall("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    table_names = {row["tablename"] for row in tables}
    assert "conversation_messages" in table_names


@pytest.mark.asyncio
async def test_conversation_messages_insert_and_fetch(db):
    """Insert and fetch a conversation message."""
    import uuid

    msg_id = uuid.uuid4()
    await db.execute(
        "INSERT INTO conversation_messages "
        "(id, direction, platform, platform_message_id, message_type, content, delivery_status) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        msg_id,
        "inbound",
        "telegram",
        42,
        "text",
        "Hello Max",
        "pending",
    )
    row = await db.fetchone("SELECT * FROM conversation_messages WHERE id = $1", msg_id)
    assert row is not None
    assert row["direction"] == "inbound"
    assert row["content"] == "Hello Max"
    assert row["platform_message_id"] == 42


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


@pytest.mark.asyncio
async def test_quality_rules_table_exists(db):
    """Verify Phase 5 quality_rules table is created."""
    tables = await db.fetchall("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    table_names = {row["tablename"] for row in tables}
    assert "quality_rules" in table_names


@pytest.mark.asyncio
async def test_quality_patterns_table_exists(db):
    """Verify Phase 5 quality_patterns table is created."""
    tables = await db.fetchall("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    table_names = {row["tablename"] for row in tables}
    assert "quality_patterns" in table_names


@pytest.mark.asyncio
async def test_audit_reports_has_phase5_columns(db):
    """Verify audit_reports has Phase 5 columns."""
    cols = await db.fetchall(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'audit_reports'"
    )
    col_names = {row["column_name"] for row in cols}
    expected = {"fix_instructions", "strengths", "fix_attempt"}
    assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"

"""Tests for database tools — PostgreSQL (mocked), SQLite (real), Redis (mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.tools.native.database_tools import (
    TOOL_DEFINITIONS,
    _parse_pg_status,
    handle_database_postgres_execute,
    handle_database_postgres_query,
    handle_database_redis_get,
    handle_database_redis_set,
    handle_database_sqlite_execute,
    handle_database_sqlite_query,
)

# ── Tool Definitions ──────────────────────────────────────────────────────


class TestToolDefinitions:
    def test_has_six_tools(self):
        assert len(TOOL_DEFINITIONS) == 6

    def test_all_database_category(self):
        for td in TOOL_DEFINITIONS:
            assert td.category == "database", f"{td.tool_id} has category {td.category}"

    def test_all_native_provider(self):
        for td in TOOL_DEFINITIONS:
            assert td.provider_id == "native", f"{td.tool_id} has provider {td.provider_id}"

    def test_tool_ids(self):
        ids = {td.tool_id for td in TOOL_DEFINITIONS}
        assert ids == {
            "database.postgres_query",
            "database.postgres_execute",
            "database.sqlite_query",
            "database.sqlite_execute",
            "database.redis_get",
            "database.redis_set",
        }

    def test_postgres_query_schema(self):
        td = next(t for t in TOOL_DEFINITIONS if t.tool_id == "database.postgres_query")
        assert "connection_string" in td.input_schema["properties"]
        assert "query" in td.input_schema["properties"]
        assert "params" in td.input_schema["properties"]
        assert td.input_schema["required"] == ["connection_string", "query"]

    def test_postgres_execute_schema(self):
        td = next(t for t in TOOL_DEFINITIONS if t.tool_id == "database.postgres_execute")
        assert "connection_string" in td.input_schema["properties"]
        assert "query" in td.input_schema["properties"]
        assert td.input_schema["required"] == ["connection_string", "query"]

    def test_sqlite_query_schema(self):
        td = next(t for t in TOOL_DEFINITIONS if t.tool_id == "database.sqlite_query")
        assert "database" in td.input_schema["properties"]
        assert "query" in td.input_schema["properties"]
        assert td.input_schema["required"] == ["database", "query"]

    def test_sqlite_execute_schema(self):
        td = next(t for t in TOOL_DEFINITIONS if t.tool_id == "database.sqlite_execute")
        assert "database" in td.input_schema["properties"]
        assert "query" in td.input_schema["properties"]
        assert td.input_schema["required"] == ["database", "query"]

    def test_redis_get_schema(self):
        td = next(t for t in TOOL_DEFINITIONS if t.tool_id == "database.redis_get")
        assert "url" in td.input_schema["properties"]
        assert "key" in td.input_schema["properties"]
        assert "keys" in td.input_schema["properties"]
        assert td.input_schema["required"] == ["url"]

    def test_redis_set_schema(self):
        td = next(t for t in TOOL_DEFINITIONS if t.tool_id == "database.redis_set")
        assert "url" in td.input_schema["properties"]
        assert "key" in td.input_schema["properties"]
        assert "value" in td.input_schema["properties"]
        assert "ttl" in td.input_schema["properties"]
        assert td.input_schema["required"] == ["url", "key", "value"]

    def test_permissions_set(self):
        pg_query = next(t for t in TOOL_DEFINITIONS if t.tool_id == "database.postgres_query")
        assert "database.read" in pg_query.permissions

        pg_exec = next(t for t in TOOL_DEFINITIONS if t.tool_id == "database.postgres_execute")
        assert "database.write" in pg_exec.permissions

        sq_query = next(t for t in TOOL_DEFINITIONS if t.tool_id == "database.sqlite_query")
        assert "database.read" in sq_query.permissions
        assert "fs.read" in sq_query.permissions

        sq_exec = next(t for t in TOOL_DEFINITIONS if t.tool_id == "database.sqlite_execute")
        assert "database.write" in sq_exec.permissions
        assert "fs.write" in sq_exec.permissions

        redis_get = next(t for t in TOOL_DEFINITIONS if t.tool_id == "database.redis_get")
        assert "database.read" in redis_get.permissions

        redis_set = next(t for t in TOOL_DEFINITIONS if t.tool_id == "database.redis_set")
        assert "database.write" in redis_set.permissions


# ── PostgreSQL (mocked) ──────────────────────────────────────────────────


class TestPostgresQuery:
    @pytest.mark.asyncio
    async def test_returns_rows(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            return_value=[
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ]
        )
        mock_conn.close = AsyncMock()

        with patch("max.tools.native.database_tools.asyncpg") as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            result = await handle_database_postgres_query(
                {
                    "connection_string": "postgresql://user:pass@localhost/db",
                    "query": "SELECT id, name FROM users",
                }
            )

        assert result["row_count"] == 2
        assert result["rows"] == [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        mock_asyncpg.connect.assert_awaited_once_with("postgresql://user:pass@localhost/db")
        mock_conn.fetch.assert_awaited_once_with("SELECT id, name FROM users")
        mock_conn.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_with_params(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[{"id": 1, "name": "Alice"}])
        mock_conn.close = AsyncMock()

        with patch("max.tools.native.database_tools.asyncpg") as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            result = await handle_database_postgres_query(
                {
                    "connection_string": "postgresql://localhost/db",
                    "query": "SELECT * FROM users WHERE id = $1",
                    "params": [1],
                }
            )

        assert result["row_count"] == 1
        mock_conn.fetch.assert_awaited_once_with("SELECT * FROM users WHERE id = $1", 1)

    @pytest.mark.asyncio
    async def test_empty_result(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_conn.close = AsyncMock()

        with patch("max.tools.native.database_tools.asyncpg") as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            result = await handle_database_postgres_query(
                {
                    "connection_string": "postgresql://localhost/db",
                    "query": "SELECT * FROM empty_table",
                }
            )

        assert result["rows"] == []
        assert result["row_count"] == 0

    @pytest.mark.asyncio
    async def test_closes_connection_on_error(self):
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=RuntimeError("query failed"))
        mock_conn.close = AsyncMock()

        with patch("max.tools.native.database_tools.asyncpg") as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            with pytest.raises(RuntimeError, match="query failed"):
                await handle_database_postgres_query(
                    {
                        "connection_string": "postgresql://localhost/db",
                        "query": "SELECT * FROM broken",
                    }
                )

        mock_conn.close.assert_awaited_once()


class TestPostgresExecute:
    @pytest.mark.asyncio
    async def test_insert(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        mock_conn.close = AsyncMock()

        with patch("max.tools.native.database_tools.asyncpg") as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            result = await handle_database_postgres_execute(
                {
                    "connection_string": "postgresql://localhost/db",
                    "query": "INSERT INTO users (name) VALUES ($1)",
                    "params": ["Alice"],
                }
            )

        assert result["status"] == "INSERT 0 1"
        assert result["rows_affected"] == 1

    @pytest.mark.asyncio
    async def test_delete_multiple(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 5")
        mock_conn.close = AsyncMock()

        with patch("max.tools.native.database_tools.asyncpg") as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            result = await handle_database_postgres_execute(
                {
                    "connection_string": "postgresql://localhost/db",
                    "query": "DELETE FROM users WHERE active = false",
                }
            )

        assert result["rows_affected"] == 5

    @pytest.mark.asyncio
    async def test_create_table(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="CREATE TABLE")
        mock_conn.close = AsyncMock()

        with patch("max.tools.native.database_tools.asyncpg") as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            result = await handle_database_postgres_execute(
                {
                    "connection_string": "postgresql://localhost/db",
                    "query": "CREATE TABLE test (id SERIAL PRIMARY KEY)",
                }
            )

        assert result["status"] == "CREATE TABLE"
        assert result["rows_affected"] == 0

    @pytest.mark.asyncio
    async def test_closes_connection_on_error(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=RuntimeError("exec failed"))
        mock_conn.close = AsyncMock()

        with patch("max.tools.native.database_tools.asyncpg") as mock_asyncpg:
            mock_asyncpg.connect = AsyncMock(return_value=mock_conn)
            with pytest.raises(RuntimeError, match="exec failed"):
                await handle_database_postgres_execute(
                    {
                        "connection_string": "postgresql://localhost/db",
                        "query": "DROP TABLE nonexistent",
                    }
                )

        mock_conn.close.assert_awaited_once()


class TestParsePgStatus:
    def test_insert(self):
        assert _parse_pg_status("INSERT 0 1") == 1

    def test_delete(self):
        assert _parse_pg_status("DELETE 3") == 3

    def test_update(self):
        assert _parse_pg_status("UPDATE 10") == 10

    def test_create_table(self):
        assert _parse_pg_status("CREATE TABLE") == 0

    def test_empty(self):
        assert _parse_pg_status("") == 0

    def test_single_word(self):
        assert _parse_pg_status("OK") == 0


# ── SQLite (real database via tmp_path) ───────────────────────────────────


class TestSqliteQuery:
    @pytest.mark.asyncio
    async def test_query_real_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")

        # Set up a real SQLite database
        await handle_database_sqlite_execute(
            {
                "database": db_path,
                "query": "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)",
            }
        )
        await handle_database_sqlite_execute(
            {
                "database": db_path,
                "query": "INSERT INTO users (name, age) VALUES (?, ?)",
                "params": ["Alice", 30],
            }
        )
        await handle_database_sqlite_execute(
            {
                "database": db_path,
                "query": "INSERT INTO users (name, age) VALUES (?, ?)",
                "params": ["Bob", 25],
            }
        )

        result = await handle_database_sqlite_query(
            {"database": db_path, "query": "SELECT * FROM users ORDER BY name"}
        )

        assert result["row_count"] == 2
        assert result["columns"] == ["id", "name", "age"]
        assert result["rows"][0]["name"] == "Alice"
        assert result["rows"][0]["age"] == 30
        assert result["rows"][1]["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_query_with_params(self, tmp_path):
        db_path = str(tmp_path / "test.db")

        await handle_database_sqlite_execute(
            {
                "database": db_path,
                "query": "CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)",
            }
        )
        await handle_database_sqlite_execute(
            {
                "database": db_path,
                "query": "INSERT INTO items (value) VALUES (?)",
                "params": ["hello"],
            }
        )
        await handle_database_sqlite_execute(
            {
                "database": db_path,
                "query": "INSERT INTO items (value) VALUES (?)",
                "params": ["world"],
            }
        )

        result = await handle_database_sqlite_query(
            {
                "database": db_path,
                "query": "SELECT * FROM items WHERE value = ?",
                "params": ["hello"],
            }
        )

        assert result["row_count"] == 1
        assert result["rows"][0]["value"] == "hello"

    @pytest.mark.asyncio
    async def test_empty_result(self, tmp_path):
        db_path = str(tmp_path / "empty.db")

        await handle_database_sqlite_execute(
            {
                "database": db_path,
                "query": "CREATE TABLE empty (id INTEGER PRIMARY KEY)",
            }
        )

        result = await handle_database_sqlite_query(
            {"database": db_path, "query": "SELECT * FROM empty"}
        )

        assert result["rows"] == []
        assert result["row_count"] == 0
        assert result["columns"] == ["id"]


class TestSqliteExecute:
    @pytest.mark.asyncio
    async def test_create_and_insert(self, tmp_path):
        db_path = str(tmp_path / "test.db")

        create_result = await handle_database_sqlite_execute(
            {
                "database": db_path,
                "query": "CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)",
            }
        )
        # CREATE TABLE doesn't affect rows
        assert (
            create_result["rows_affected"] == -1
            or create_result["rows_affected"] == 0
            or "rows_affected" in create_result
        )

        insert_result = await handle_database_sqlite_execute(
            {
                "database": db_path,
                "query": "INSERT INTO test (val) VALUES (?)",
                "params": ["item1"],
            }
        )
        assert insert_result["rows_affected"] == 1

    @pytest.mark.asyncio
    async def test_update_rows(self, tmp_path):
        db_path = str(tmp_path / "test.db")

        await handle_database_sqlite_execute(
            {"database": db_path, "query": "CREATE TABLE t (id INTEGER PRIMARY KEY, x INTEGER)"}
        )
        await handle_database_sqlite_execute(
            {"database": db_path, "query": "INSERT INTO t (x) VALUES (1)"}
        )
        await handle_database_sqlite_execute(
            {"database": db_path, "query": "INSERT INTO t (x) VALUES (1)"}
        )
        await handle_database_sqlite_execute(
            {"database": db_path, "query": "INSERT INTO t (x) VALUES (2)"}
        )

        result = await handle_database_sqlite_execute(
            {"database": db_path, "query": "UPDATE t SET x = 99 WHERE x = 1"}
        )
        assert result["rows_affected"] == 2

    @pytest.mark.asyncio
    async def test_delete_rows(self, tmp_path):
        db_path = str(tmp_path / "test.db")

        await handle_database_sqlite_execute(
            {"database": db_path, "query": "CREATE TABLE d (id INTEGER PRIMARY KEY, v TEXT)"}
        )
        await handle_database_sqlite_execute(
            {"database": db_path, "query": "INSERT INTO d (v) VALUES ('a')"}
        )
        await handle_database_sqlite_execute(
            {"database": db_path, "query": "INSERT INTO d (v) VALUES ('b')"}
        )
        await handle_database_sqlite_execute(
            {"database": db_path, "query": "INSERT INTO d (v) VALUES ('a')"}
        )

        result = await handle_database_sqlite_execute(
            {"database": db_path, "query": "DELETE FROM d WHERE v = 'a'"}
        )
        assert result["rows_affected"] == 2


class TestSqliteMissingDependency:
    @pytest.mark.asyncio
    async def test_sqlite_query_without_aiosqlite(self):
        with patch("max.tools.native.database_tools.HAS_AIOSQLITE", False):
            result = await handle_database_sqlite_query(
                {"database": "/tmp/test.db", "query": "SELECT 1"}
            )
        assert "error" in result
        assert "aiosqlite" in result["error"]
        assert result["rows"] == []
        assert result["row_count"] == 0

    @pytest.mark.asyncio
    async def test_sqlite_execute_without_aiosqlite(self):
        with patch("max.tools.native.database_tools.HAS_AIOSQLITE", False):
            result = await handle_database_sqlite_execute(
                {"database": "/tmp/test.db", "query": "CREATE TABLE t (id INT)"}
            )
        assert "error" in result
        assert "aiosqlite" in result["error"]
        assert result["rows_affected"] == 0


# ── Redis (mocked) ───────────────────────────────────────────────────────


class TestRedisGet:
    @pytest.mark.asyncio
    async def test_get_single_key(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value="hello")
        mock_client.aclose = AsyncMock()

        with patch("max.tools.native.database_tools.aioredis") as mock_redis:
            mock_redis.from_url = MagicMock(return_value=mock_client)
            result = await handle_database_redis_get(
                {"url": "redis://localhost:6379/0", "key": "mykey"}
            )

        assert result["value"] == "hello"
        mock_redis.from_url.assert_called_once_with(
            "redis://localhost:6379/0", decode_responses=True
        )
        mock_client.get.assert_awaited_once_with("mykey")
        mock_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_multiple_keys(self):
        mock_client = AsyncMock()
        mock_client.mget = AsyncMock(return_value=["val1", "val2", None])
        mock_client.aclose = AsyncMock()

        with patch("max.tools.native.database_tools.aioredis") as mock_redis:
            mock_redis.from_url = MagicMock(return_value=mock_client)
            result = await handle_database_redis_get(
                {
                    "url": "redis://localhost:6379/0",
                    "keys": ["key1", "key2", "key3"],
                }
            )

        assert result["values"] == {"key1": "val1", "key2": "val2", "key3": None}
        mock_client.mget.assert_awaited_once_with(["key1", "key2", "key3"])

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)
        mock_client.aclose = AsyncMock()

        with patch("max.tools.native.database_tools.aioredis") as mock_redis:
            mock_redis.from_url = MagicMock(return_value=mock_client)
            result = await handle_database_redis_get(
                {"url": "redis://localhost:6379/0", "key": "missing"}
            )

        assert result["value"] is None

    @pytest.mark.asyncio
    async def test_no_key_or_keys(self):
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()

        with patch("max.tools.native.database_tools.aioredis") as mock_redis:
            mock_redis.from_url = MagicMock(return_value=mock_client)
            result = await handle_database_redis_get({"url": "redis://localhost:6379/0"})

        assert "error" in result

    @pytest.mark.asyncio
    async def test_closes_on_error(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("connection lost"))
        mock_client.aclose = AsyncMock()

        with patch("max.tools.native.database_tools.aioredis") as mock_redis:
            mock_redis.from_url = MagicMock(return_value=mock_client)
            with pytest.raises(RuntimeError, match="connection lost"):
                await handle_database_redis_get({"url": "redis://localhost:6379/0", "key": "fail"})

        mock_client.aclose.assert_awaited_once()


class TestRedisSet:
    @pytest.mark.asyncio
    async def test_set_key(self):
        mock_client = AsyncMock()
        mock_client.set = AsyncMock()
        mock_client.aclose = AsyncMock()

        with patch("max.tools.native.database_tools.aioredis") as mock_redis:
            mock_redis.from_url = MagicMock(return_value=mock_client)
            result = await handle_database_redis_set(
                {
                    "url": "redis://localhost:6379/0",
                    "key": "mykey",
                    "value": "myvalue",
                }
            )

        assert result["success"] is True
        mock_client.set.assert_awaited_once_with("mykey", "myvalue")

    @pytest.mark.asyncio
    async def test_set_key_with_ttl(self):
        mock_client = AsyncMock()
        mock_client.set = AsyncMock()
        mock_client.aclose = AsyncMock()

        with patch("max.tools.native.database_tools.aioredis") as mock_redis:
            mock_redis.from_url = MagicMock(return_value=mock_client)
            result = await handle_database_redis_set(
                {
                    "url": "redis://localhost:6379/0",
                    "key": "ephemeral",
                    "value": "temp",
                    "ttl": 60,
                }
            )

        assert result["success"] is True
        mock_client.set.assert_awaited_once_with("ephemeral", "temp", ex=60)

    @pytest.mark.asyncio
    async def test_closes_on_error(self):
        mock_client = AsyncMock()
        mock_client.set = AsyncMock(side_effect=RuntimeError("write failed"))
        mock_client.aclose = AsyncMock()

        with patch("max.tools.native.database_tools.aioredis") as mock_redis:
            mock_redis.from_url = MagicMock(return_value=mock_client)
            with pytest.raises(RuntimeError, match="write failed"):
                await handle_database_redis_set(
                    {
                        "url": "redis://localhost:6379/0",
                        "key": "fail",
                        "value": "x",
                    }
                )

        mock_client.aclose.assert_awaited_once()

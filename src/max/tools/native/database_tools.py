"""Database tools — PostgreSQL, SQLite, and Redis operations."""

from __future__ import annotations

from typing import Any

from max.tools.registry import ToolDefinition

try:
    import asyncpg

    HAS_ASYNCPG = True
except ImportError:
    asyncpg = None  # type: ignore[assignment]
    HAS_ASYNCPG = False

try:
    import redis.asyncio as aioredis

    HAS_REDIS = True
except ImportError:
    aioredis = None  # type: ignore[assignment]
    HAS_REDIS = False

try:
    import aiosqlite

    HAS_AIOSQLITE = True
except ImportError:
    HAS_AIOSQLITE = False

TOOL_DEFINITIONS = [
    # ── PostgreSQL ────────────────────────────────────────────────────────
    ToolDefinition(
        tool_id="database.postgres_query",
        category="database",
        description="Execute a SELECT query on PostgreSQL and return rows.",
        permissions=["database.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "connection_string": {
                    "type": "string",
                    "description": "PostgreSQL connection URI (e.g. postgresql://user:pass@host/db)",
                },
                "query": {
                    "type": "string",
                    "description": "SQL SELECT query to execute",
                },
                "params": {
                    "type": "array",
                    "description": "Positional query parameters ($1, $2, ...)",
                },
            },
            "required": ["connection_string", "query"],
        },
    ),
    ToolDefinition(
        tool_id="database.postgres_execute",
        category="database",
        description="Execute a DML/DDL statement on PostgreSQL (INSERT, UPDATE, etc.).",
        permissions=["database.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "connection_string": {
                    "type": "string",
                    "description": "PostgreSQL connection URI",
                },
                "query": {
                    "type": "string",
                    "description": "SQL DML/DDL statement to execute",
                },
                "params": {
                    "type": "array",
                    "description": "Positional query parameters ($1, $2, ...)",
                },
            },
            "required": ["connection_string", "query"],
        },
    ),
    # ── SQLite ────────────────────────────────────────────────────────────
    ToolDefinition(
        tool_id="database.sqlite_query",
        category="database",
        description="Execute a SELECT query on a SQLite database file.",
        permissions=["database.read", "fs.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "description": "Path to the SQLite database file",
                },
                "query": {
                    "type": "string",
                    "description": "SQL SELECT query to execute",
                },
                "params": {
                    "type": "array",
                    "description": "Positional query parameters (?, ?, ...)",
                },
            },
            "required": ["database", "query"],
        },
    ),
    ToolDefinition(
        tool_id="database.sqlite_execute",
        category="database",
        description="Execute a DML/DDL statement on a SQLite database file.",
        permissions=["database.write", "fs.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "description": "Path to the SQLite database file",
                },
                "query": {
                    "type": "string",
                    "description": "SQL DML/DDL statement to execute",
                },
                "params": {
                    "type": "array",
                    "description": "Positional query parameters (?, ?, ...)",
                },
            },
            "required": ["database", "query"],
        },
    ),
    # ── Redis ─────────────────────────────────────────────────────────────
    ToolDefinition(
        tool_id="database.redis_get",
        category="database",
        description="Get one or more Redis keys.",
        permissions=["database.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Redis connection URL (e.g. redis://localhost:6379/0)",
                },
                "key": {
                    "type": "string",
                    "description": "Single key to get",
                },
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Multiple keys to get (use instead of key for batch)",
                },
            },
            "required": ["url"],
        },
    ),
    ToolDefinition(
        tool_id="database.redis_set",
        category="database",
        description="Set a Redis key to a value with optional TTL.",
        permissions=["database.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Redis connection URL",
                },
                "key": {
                    "type": "string",
                    "description": "Key to set",
                },
                "value": {
                    "type": "string",
                    "description": "Value to set",
                },
                "ttl": {
                    "type": "integer",
                    "description": "Time to live in seconds (optional)",
                },
            },
            "required": ["url", "key", "value"],
        },
    ),
]


# ── PostgreSQL handlers ───────────────────────────────────────────────────


async def handle_database_postgres_query(inputs: dict[str, Any]) -> dict[str, Any]:
    """Execute a SELECT query on PostgreSQL and return rows."""
    if not HAS_ASYNCPG:
        return {"error": "asyncpg is not installed. Install with: pip install asyncpg"}
    try:
        conn = await asyncpg.connect(inputs["connection_string"])
        try:
            params = inputs.get("params") or []
            records = await conn.fetch(inputs["query"], *params)
            rows = [dict(r) for r in records]
            return {"rows": rows, "row_count": len(rows)}
        finally:
            await conn.close()
    except Exception as e:
        return {"error": str(e)}


async def handle_database_postgres_execute(inputs: dict[str, Any]) -> dict[str, Any]:
    """Execute a DML/DDL statement on PostgreSQL."""
    if not HAS_ASYNCPG:
        return {"error": "asyncpg is not installed. Install with: pip install asyncpg"}
    try:
        conn = await asyncpg.connect(inputs["connection_string"])
        try:
            params = inputs.get("params") or []
            status = await conn.execute(inputs["query"], *params)
            # asyncpg returns a status string like "INSERT 0 1" or "DELETE 3"
            rows_affected = _parse_pg_status(status)
            return {"status": status, "rows_affected": rows_affected}
        finally:
            await conn.close()
    except Exception as e:
        return {"error": str(e)}


def _parse_pg_status(status: str) -> int:
    """Parse the row count from a PostgreSQL command status string.

    Examples:
        "INSERT 0 1" -> 1
        "DELETE 3"   -> 3
        "UPDATE 5"   -> 5
        "CREATE TABLE" -> 0
    """
    parts = status.split()
    if len(parts) >= 2:
        try:
            return int(parts[-1])
        except ValueError:
            return 0
    return 0


# ── SQLite handlers ───────────────────────────────────────────────────────


async def handle_database_sqlite_query(inputs: dict[str, Any]) -> dict[str, Any]:
    """Execute a SELECT query on a SQLite database file."""
    if not HAS_AIOSQLITE:
        return {
            "error": "aiosqlite is not installed. Install it with: pip install aiosqlite",
            "rows": [],
            "columns": [],
            "row_count": 0,
        }
    async with aiosqlite.connect(inputs["database"]) as db:
        db.row_factory = aiosqlite.Row
        params = inputs.get("params") or []
        cursor = await db.execute(inputs["query"], params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        raw_rows = await cursor.fetchall()
        rows = [dict(zip(columns, row)) for row in raw_rows]
        return {"rows": rows, "columns": columns, "row_count": len(rows)}


async def handle_database_sqlite_execute(inputs: dict[str, Any]) -> dict[str, Any]:
    """Execute a DML/DDL statement on a SQLite database file."""
    if not HAS_AIOSQLITE:
        return {
            "error": "aiosqlite is not installed. Install it with: pip install aiosqlite",
            "rows_affected": 0,
        }
    async with aiosqlite.connect(inputs["database"]) as db:
        params = inputs.get("params") or []
        cursor = await db.execute(inputs["query"], params)
        await db.commit()
        return {"rows_affected": cursor.rowcount}


# ── Redis handlers ────────────────────────────────────────────────────────


async def handle_database_redis_get(inputs: dict[str, Any]) -> dict[str, Any]:
    """Get one or more Redis keys."""
    if not HAS_REDIS:
        return {"error": "redis is not installed. Install with: pip install redis"}
    try:
        client = aioredis.from_url(inputs["url"], decode_responses=True)
        try:
            keys = inputs.get("keys")
            if keys:
                values = await client.mget(keys)
                return {"values": dict(zip(keys, values))}
            key = inputs.get("key")
            if not key:
                return {"error": "Either 'key' or 'keys' must be provided"}
            value = await client.get(key)
            return {"value": value}
        finally:
            await client.aclose()
    except Exception as e:
        return {"error": str(e)}


async def handle_database_redis_set(inputs: dict[str, Any]) -> dict[str, Any]:
    """Set a Redis key to a value with optional TTL."""
    if not HAS_REDIS:
        return {"error": "redis is not installed. Install with: pip install redis"}
    try:
        client = aioredis.from_url(inputs["url"], decode_responses=True)
        try:
            ttl = inputs.get("ttl")
            if ttl:
                await client.set(inputs["key"], inputs["value"], ex=ttl)
            else:
                await client.set(inputs["key"], inputs["value"])
            return {"success": True}
        finally:
            await client.aclose()
    except Exception as e:
        return {"error": str(e)}

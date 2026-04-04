"""Async PostgreSQL database layer with connection pooling."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    """Async PostgreSQL client backed by a connection pool.

    Usage::

        db = Database(dsn="postgresql://max:password@localhost:5432/max")
        await db.connect()
        row = await db.fetchone("SELECT 1 AS val")
        await db.close()
    """

    def __init__(self, dsn: str, min_pool_size: int = 2, max_pool_size: int = 10):
        self._dsn = dsn
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Create the connection pool."""
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._min_pool_size,
            max_size=self._max_pool_size,
        )
        logger.info("Connected to PostgreSQL")

    def _get_pool(self) -> asyncpg.Pool:
        """Return the connection pool, raising if not yet connected."""
        if self._pool is None:
            raise RuntimeError("Database.connect() must be called before executing queries")
        return self._pool

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            logger.info("Disconnected from PostgreSQL")

    async def init_schema(self) -> None:
        """Read and execute schema.sql to initialize all tables and indexes."""
        schema_sql = SCHEMA_PATH.read_text()
        async with self._get_pool().acquire() as conn:
            await conn.execute(schema_sql)
        logger.info("Database schema initialized")

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a query and return the status string (e.g. 'INSERT 0 1')."""
        async with self._get_pool().acquire() as conn:
            return await conn.execute(query, *args)

    async def fetchone(self, query: str, *args: Any) -> dict[str, Any] | None:
        """Fetch a single row as a dict, or None if no rows match."""
        async with self._get_pool().acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def fetchall(self, query: str, *args: Any) -> list[dict[str, Any]]:
        """Fetch all matching rows as a list of dicts."""
        async with self._get_pool().acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

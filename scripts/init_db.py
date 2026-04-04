"""Initialize the Max database schema.

Run this script after starting PostgreSQL via Docker Compose to create
all required tables, indexes, and extensions (including pgvector).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from max.config import Settings
from max.db.postgres import Database


async def main():
    settings = Settings()
    db = Database(dsn=settings.postgres_dsn)
    await db.connect()
    await db.init_schema()
    print("Schema initialized successfully.")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())

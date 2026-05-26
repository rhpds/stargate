"""Database layer — asyncpg with in-memory fallback for testing."""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
_pool = None
_use_memory = True

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


async def init_db():
    """Initialize asyncpg pool and run migrations, or fall back to in-memory."""
    global _pool, _use_memory
    if not DATABASE_URL:
        logger.info("DATABASE_URL not set — using in-memory storage")
        _use_memory = True
        return

    try:
        import asyncpg
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        _use_memory = False
        await _run_migrations()
        logger.info("PostgreSQL connected, migrations applied")
    except Exception as e:
        logger.warning("PostgreSQL unavailable, falling back to in-memory: %s", e)
        _pool = None
        _use_memory = True


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool():
    return _pool


def is_memory_mode() -> bool:
    return _use_memory


def set_memory_mode():
    """Force in-memory mode (for testing)."""
    global _use_memory, _pool
    _use_memory = True
    _pool = None


async def _run_migrations():
    if not _pool or not MIGRATIONS_DIR.is_dir():
        return
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS applied_migrations (
                id SERIAL PRIMARY KEY,
                filename TEXT UNIQUE NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT now()
            )
        """)
        applied = {row["filename"] for row in await conn.fetch("SELECT filename FROM applied_migrations")}
        for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if sql_file.name not in applied:
                sql = sql_file.read_text()
                await conn.execute(sql)
                await conn.execute("INSERT INTO applied_migrations (filename) VALUES ($1)", sql_file.name)
                logger.info("Applied migration: %s", sql_file.name)

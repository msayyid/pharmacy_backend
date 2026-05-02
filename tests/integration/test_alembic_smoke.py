"""End-to-end Alembic round-trip — upgrade/downgrade against the test DB.

Alembic's env.py calls ``asyncio.run(run_migrations_online())``. From an
async test (which is already inside an event loop), that raises
``RuntimeError: asyncio.run() cannot be called from a running event loop``.
Fix: drive ``alembic.command`` via ``asyncio.to_thread`` so it runs in a
worker thread with no running loop of its own.

The ``finally`` block restores the DB to head state so subsequent tests
in the same pytest session see the migrations they expect.
"""

from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

pytestmark = pytest.mark.integration


async def _users_table_exists() -> bool:
    """Query via a fresh NullPool engine so each call is loop-safe."""
    e = create_async_engine(
        str(get_settings().mysql_dsn),
        poolclass=NullPool,
        connect_args={"charset": "utf8mb4"},
    )
    try:
        session_factory = async_sessionmaker(e, expire_on_commit=False)
        async with session_factory() as s:
            r = await s.execute(text("SHOW TABLES LIKE 'users'"))
            return r.first() is not None
    finally:
        await e.dispose()


async def _alembic(action: str, cfg: Config, target: str) -> None:
    """Run a sync alembic command in a thread to avoid nested event loops."""
    fn = getattr(command, action)
    await asyncio.to_thread(fn, cfg, target)


async def test_alembic_round_trip(alembic_config: Config) -> None:
    """``downgrade base`` → ``upgrade head`` → ``downgrade base`` → restore head."""
    try:
        await _alembic("downgrade", alembic_config, "base")
        assert not await _users_table_exists(), "users should be gone after downgrade base"

        await _alembic("upgrade", alembic_config, "head")
        assert await _users_table_exists(), "users should exist after upgrade head"

        await _alembic("downgrade", alembic_config, "base")
        assert not await _users_table_exists(), "users should be gone after second downgrade"
    finally:
        # Restore the session-scope expectation: DB is at head.
        await _alembic("upgrade", alembic_config, "head")

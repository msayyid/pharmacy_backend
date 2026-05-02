"""Async database engine and session factory.

* :data:`engine` — ``AsyncEngine`` configured from ``settings.mysql_dsn``.
* :data:`SessionLocal` — ``async_sessionmaker`` with ``expire_on_commit=False``.
* :func:`get_db` — FastAPI dependency. One session per request, commits on
  success / rolls back on exception.
* :func:`session_scope` — async context manager for workers and scripts.

Reference: BACKEND_BLUEPRINT.md §7.

**Trap:** ``expire_on_commit=False`` means accessing model attributes AFTER
``session.commit()`` returns the in-memory cached values, NOT a fresh DB
read. If a column depends on a server-side default (``utc_timestamp(6)``)
or an ``onupdate`` trigger, the in-memory value may lag the row in the
database until the next ``session.refresh(obj)`` or fresh query. This is
the right trade-off for async (avoids `MissingGreenlet` on serialization)
but expect occasional stale-cache surprises during refactors.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_settings = get_settings()

engine: AsyncEngine = create_async_engine(
    str(_settings.mysql_dsn),
    echo=_settings.db_echo,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_recycle=_settings.db_pool_recycle_seconds,
    pool_pre_ping=True,
    future=True,
    connect_args={"charset": "utf8mb4"},
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. One session per request, commit/rollback on exit."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Context manager for workers, scripts, and tests (no FastAPI lifecycle)."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

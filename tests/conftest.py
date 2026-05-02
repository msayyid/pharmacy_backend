"""Test fixtures.

* Phase 1 — load ``.env.test``, autouse settings-cache reset, ``httpx.AsyncClient``.
* Phase 2 — Alembic-managed DB at session scope; ``AsyncSession`` per test.

Tests that need DB access request the ``session`` fixture, which transitively
brings up ``_migrated_db`` (session-scoped) once per test session.

For the DB fixtures to work, ``mysql-test`` must be running on port 3307:
``make docker-up-test``. CI does this automatically.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# ─── Env loading (must run before any app.* import) ───────────────────────────


def _load_env_test() -> None:
    """Load .env.test BEFORE any ``app.*`` import."""
    env_path = Path(__file__).parent.parent / ".env.test"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env_test()


# ─── Phase 1 fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Clear settings cache so per-test ``monkeypatch.setenv`` takes effect."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client against a fresh FastAPI app instance."""
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ─── Phase 2 — DB fixtures ────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    """Alembic Config pointing at ``alembic.ini`` (which reads ``MYSQL_DSN`` via env.py)."""
    return Config("alembic.ini")


@pytest.fixture(scope="session")
def _migrated_db(alembic_config: Config) -> Iterator[None]:
    """Apply migrations once at session start; downgrade to base at session end.

    Sync fixture — Alembic's command API is sync, and that's the only way to
    drive it without resorting to a sub-thread. Tests that need DB access
    request ``session``, which transitively pulls in this fixture.
    """
    # Defensive: ensure clean state regardless of prior session aborts.
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    yield
    command.downgrade(alembic_config, "base")


@pytest_asyncio.fixture
async def redis_clean() -> AsyncIterator[None]:
    """Per-test Redis: defensive close, init, FLUSHDB, yield, close.

    Per-test init/close avoids the pytest-asyncio function-loop / module-
    state mismatch (same root cause as the DB ``NullPool`` decision).
    Cost: ~100ms per test; acceptable for the small number of integration
    tests that need Redis.
    """
    from app.core.config import get_settings
    from app.core.redis import close_redis, get_redis, init_redis

    await close_redis()  # defensive: clear any leaked module state
    await init_redis(get_settings())
    r = get_redis()
    await r.flushdb()
    yield
    await close_redis()


@pytest_asyncio.fixture
async def session(_migrated_db: None) -> AsyncIterator[AsyncSession]:
    """One ``AsyncSession`` per test, rolled back at the end.

    Uses a per-test engine with ``NullPool`` to avoid the pytest-asyncio
    function-scoped-loop vs module-level engine mismatch ("Future attached
    to a different loop"). Slightly slower than reusing connections, but
    correct — and tests aren't perf-critical.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import get_settings

    test_engine = create_async_engine(
        str(get_settings().mysql_dsn),
        poolclass=NullPool,
        connect_args={"charset": "utf8mb4"},
    )
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    try:
        async with session_factory() as s:
            try:
                yield s
            finally:
                await s.rollback()
    finally:
        await test_engine.dispose()

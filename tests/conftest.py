"""Test fixtures — Phase 1 minimum.

Loads ``.env.test`` before any ``app.*`` import, then exposes:

* ``client`` — ``httpx.AsyncClient`` against the FastAPI app via ASGI transport
* ``_reset_settings_cache`` (autouse) — clears ``get_settings`` cache between tests

Phase 2 will add DB engine + session fixtures per BACKEND_BLUEPRINT §23.2.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def _load_env_test() -> None:
    """Load .env.test BEFORE any app module is imported."""
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


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> AsyncIterator[None]:  # type: ignore[misc]
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

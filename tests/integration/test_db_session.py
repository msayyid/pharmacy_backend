"""Async session round-trip — insert and read against the placeholder ping table."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app._ping_transient import Ping

pytestmark = pytest.mark.integration


async def test_session_insert_and_read_back(session: AsyncSession) -> None:
    """Insert a Ping row, commit, query it back."""
    p = Ping(message="hello pharmacy")
    session.add(p)
    await session.flush()
    pid = p.id
    assert pid is not None

    r = await session.execute(select(Ping).where(Ping.id == pid))
    found = r.scalar_one()
    assert found.message == "hello pharmacy"


async def test_session_handles_unicode_cyrillic(session: AsyncSession) -> None:
    """utf8mb4 encodes Cyrillic correctly through the round-trip."""
    # Genuine Cyrillic — `мг` is the Russian abbreviation for milligrams.
    msg = "Парацетамол 500мг"  # noqa: RUF001  # intentional Cyrillic test data
    p = Ping(message=msg)
    session.add(p)
    await session.flush()

    r = await session.execute(select(Ping).where(Ping.id == p.id))
    found = r.scalar_one()
    assert found.message == msg

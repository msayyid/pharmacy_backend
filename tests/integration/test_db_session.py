"""Async session round-trip — insert and read against the branches table.

Phase 2 used the (now-dropped) ``ping`` placeholder; Phase 4 dropped it and
landed real domain models. This test still serves as a basic round-trip
smoke for the engine + session.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.inventory.models import Branch

pytestmark = pytest.mark.integration


async def test_session_insert_and_read_back(session: AsyncSession) -> None:
    """Insert a Branch row, flush, query it back."""
    b = Branch(
        code="TEST_BR_1",
        name="Test Branch 1",
        address="мкр Асанбай, дом 1",
    )
    session.add(b)
    await session.flush()
    assert b.id is not None

    r = await session.execute(select(Branch).where(Branch.id == b.id))
    found = r.scalar_one()
    assert found.code == "TEST_BR_1"
    assert found.name == "Test Branch 1"
    # Defaults
    assert found.city == "Bishkek"
    assert found.timezone == "Asia/Bishkek"
    assert found.is_active is True


async def test_session_handles_unicode_cyrillic(session: AsyncSession) -> None:
    """utf8mb4 encodes Cyrillic correctly through the round-trip."""
    b = Branch(
        code="TEST_BR_2",
        name="Аптека на Чуй",
        address="г. Бишкек, ул. Чуй, 100",  # noqa: RUF001
    )
    session.add(b)
    await session.flush()
    r = await session.execute(select(Branch).where(Branch.id == b.id))
    found = r.scalar_one()
    assert found.name == "Аптека на Чуй"
    assert found.address == "г. Бишкек, ул. Чуй, 100"  # noqa: RUF001

"""MySQL server is configured per BACKEND §6.1 / CLAUDE.md."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_character_set_database_is_utf8mb4(session: AsyncSession) -> None:
    r = await session.execute(text("SELECT @@character_set_database"))
    assert r.scalar_one() == "utf8mb4"


async def test_collation_database_is_0900_ai_ci(session: AsyncSession) -> None:
    r = await session.execute(text("SELECT @@collation_database"))
    assert r.scalar_one() == "utf8mb4_0900_ai_ci"


async def test_sql_mode_includes_required_strictness(session: AsyncSession) -> None:
    """sql_mode includes the modes from CLAUDE.md 'Tech stack reality checks'."""
    r = await session.execute(text("SELECT @@sql_mode"))
    mode: str = r.scalar_one()
    for required in (
        "STRICT_TRANS_TABLES",
        "NO_ZERO_DATE",
        "NO_ZERO_IN_DATE",
        "ONLY_FULL_GROUP_BY",
        "ERROR_FOR_DIVISION_BY_ZERO",
    ):
        assert required in mode, f"sql_mode missing {required}: {mode}"


async def test_ngram_token_size_is_2(session: AsyncSession) -> None:
    """ngram_token_size = 2 for Cyrillic FULLTEXT search (Phase 7)."""
    r = await session.execute(text("SELECT @@ngram_token_size"))
    assert r.scalar_one() == 2


async def test_default_storage_engine_is_innodb(session: AsyncSession) -> None:
    r = await session.execute(text("SELECT @@default_storage_engine"))
    assert r.scalar_one() == "InnoDB"

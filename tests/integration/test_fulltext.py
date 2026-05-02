"""FULLTEXT ngram smoke test for ``product_translations``.

The Phase 5 migration creates a FULLTEXT ngram index on
``(name, short_description, description)`` (token_size=2). A live MATCH
query needs the rows committed for the index to "see" them, which would
leak into other tests via the rolled-back fixture. So instead this test
asserts the index *exists* with the expected parser via
``INFORMATION_SCHEMA``. Phase 7 will run live MATCH queries against
seeded fixtures.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_product_translations_has_fulltext_ngram_index(
    session: AsyncSession,
) -> None:
    rows = (
        await session.execute(
            text(
                """
                SELECT INDEX_NAME, INDEX_TYPE
                FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'product_translations'
                  AND INDEX_TYPE = 'FULLTEXT'
                """
            )
        )
    ).all()
    assert any(r.INDEX_NAME == "ftx_pt_search" for r in rows)


async def test_fulltext_index_uses_ngram_parser(session: AsyncSession) -> None:
    """SHOW CREATE TABLE exposes the parser; assert ngram for our index."""
    row = (await session.execute(text("SHOW CREATE TABLE product_translations"))).one()
    ddl = row[1]
    assert "FULLTEXT" in ddl
    assert "ftx_pt_search" in ddl
    assert "WITH PARSER `ngram`" in ddl or "WITH PARSER ngram" in ddl

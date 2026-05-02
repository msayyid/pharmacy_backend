"""TRANSIENT — placeholder model for Phase 2 to verify the migration pipeline.

This file exists ONLY so Alembic's first ``--autogenerate`` produces a
non-empty migration. It will be removed in Phase 4 when the real domain
models land; the corresponding ``ping`` table will be dropped by a Phase 4
migration.

* DO NOT add fields here.
* DO NOT import this from production code paths.
* DO NOT reference ``Ping`` in services or schemas.

Phase 4 hand-off:

  1. Delete this file.
  2. Remove the ``import app._ping_transient  # noqa: F401`` line in
     ``migrations/env.py``.
  3. Add an Alembic migration: ``op.drop_table("ping")``.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_base import Base


class Ping(Base):
    """Transient placeholder. Removed in Phase 4 (see CHANGELOG)."""

    __tablename__ = "ping"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )

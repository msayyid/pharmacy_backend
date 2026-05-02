"""Inventory domain — repositories.

Phase 4 lands :class:`BranchRepository` only (because admin auth needs
branch lookups). Phase 6 lands ``BranchProductRepository``,
``InventoryBatchRepository``, ``StockMovementRepository`` plus the FEFO
query infrastructure.

Reference: BACKEND_BLUEPRINT.md §11.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.inventory.models import Branch


class BranchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, branch_id: int) -> Branch | None:
        stmt = select(Branch).where(Branch.id == branch_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_code(self, code: str) -> Branch | None:
        stmt = select(Branch).where(Branch.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_active(self) -> Sequence[Branch]:
        stmt = select(Branch).where(Branch.is_active.is_(True)).order_by(Branch.name)
        return (await self.session.execute(stmt)).scalars().all()

    async def add(self, branch: Branch) -> None:
        self.session.add(branch)
        await self.session.flush()

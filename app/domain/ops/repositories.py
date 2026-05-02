"""Operations domain — admin audit log repository.

Phase 5 lands the audit log writer; Phase 9 adds the read-side viewer.

Reference: PHARMACY_BLUEPRINT_2.md §8.1.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ops.models import AdminAuditLog


class AdminAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        admin_user_id: int | None,
        action: str,
        entity_type: str,
        entity_id: str | None,
        changes: dict[str, Any] | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> AdminAuditLog:
        row = AdminAuditLog(
            admin_user_id=admin_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=changes,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_paginated(
        self,
        *,
        admin_user_id: int | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[AdminAuditLog], int]:
        base = select(AdminAuditLog)
        if admin_user_id is not None:
            base = base.where(AdminAuditLog.admin_user_id == admin_user_id)
        if entity_type is not None:
            base = base.where(AdminAuditLog.entity_type == entity_type)
        if entity_id is not None:
            base = base.where(AdminAuditLog.entity_id == entity_id)
        if from_dt is not None:
            base = base.where(AdminAuditLog.created_at >= from_dt)
        if to_dt is not None:
            base = base.where(AdminAuditLog.created_at < to_dt)

        total_stmt = select(func.count()).select_from(base.subquery())
        items_stmt = base.order_by(AdminAuditLog.created_at.desc()).offset(offset).limit(limit)
        total = (await self.session.execute(total_stmt)).scalar_one()
        items = (await self.session.execute(items_stmt)).scalars().all()
        return (items, total)

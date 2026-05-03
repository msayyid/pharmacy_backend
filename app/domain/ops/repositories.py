"""Operations domain — admin audit log + search log + sms log repositories.

* Phase 5 — audit log writer.
* Phase 7 — search log writer + popular-searches read.
* Phase 9 — admin viewer endpoints (read side).
* Phase 10 — SMS log: ``create_queued`` from the enqueue site, then
  ``mark_sent`` / ``mark_failed`` from the worker after the provider
  responds.

Reference: PHARMACY_BLUEPRINT_2.md §8.1, §8.2, §8.3.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ops.models import AdminAuditLog, SearchLog, SmsLog


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


class SearchLogRepository:
    """Append-only writer + analytics reads on ``search_log`` (Phase 7)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        *,
        query: str,
        language_code: str | None,
        user_id: UUID | None,
        results_count: int,
    ) -> SearchLog:
        row = SearchLog(
            query=query,
            language_code=language_code,
            user_id=user_id,
            results_count=results_count,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def popular_queries(
        self, *, limit: int = 5, language_code: str | None = None
    ) -> Sequence[str]:
        """Top-N non-zero-result queries by frequency.

        Used as the empty-state "Try these" list. Lower-cases the
        ``query`` so casing variants collapse.
        """
        q = func.lower(SearchLog.query).label("q")
        stmt = select(q, func.count().label("c")).where(SearchLog.results_count > 0)
        if language_code is not None:
            stmt = stmt.where(SearchLog.language_code == language_code)
        stmt = stmt.group_by(q).order_by(func.count().desc()).limit(limit)
        return [row.q for row in (await self.session.execute(stmt)).all()]

    async def recent_zero_results(self, *, limit: int = 50) -> Sequence[SearchLog]:
        """Catalog-gap signal — recent searches that found nothing."""
        stmt = (
            select(SearchLog)
            .where(SearchLog.results_count == 0)
            .order_by(SearchLog.created_at.desc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()


class SmsLogRepository:
    """Append + status-update writer for ``sms_log`` (Phase 10)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_queued(
        self,
        *,
        phone: str,
        body: str,
        purpose: str,
        provider: str | None = None,
    ) -> SmsLog:
        row = SmsLog(
            phone=phone,
            body=body,
            purpose=purpose,
            provider=provider,
            status="queued",
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def mark_sent(
        self,
        sms_log_id: int,
        *,
        provider_message_id: str | None = None,
        cost: Decimal | None = None,
    ) -> None:
        row = await self.session.get(SmsLog, sms_log_id)
        if row is None:
            return
        row.status = "sent"
        row.provider_message_id = provider_message_id
        row.cost = cost
        row.sent_at = datetime.now(tz=UTC).replace(tzinfo=None)
        await self.session.flush()

    async def mark_failed(self, sms_log_id: int, *, error: str) -> None:
        row = await self.session.get(SmsLog, sms_log_id)
        if row is None:
            return
        row.status = "failed"
        row.error = error[:65000]  # TEXT cap; tenacity exception chains can balloon
        await self.session.flush()

    async def get(self, sms_log_id: int) -> SmsLog | None:
        return await self.session.get(SmsLog, sms_log_id)

    async def list_recent(
        self,
        *,
        phone: str | None = None,
        purpose: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> Sequence[SmsLog]:
        stmt = select(SmsLog)
        if phone is not None:
            stmt = stmt.where(SmsLog.phone == phone)
        if purpose is not None:
            stmt = stmt.where(SmsLog.purpose == purpose)
        if status is not None:
            stmt = stmt.where(SmsLog.status == status)
        stmt = stmt.order_by(SmsLog.created_at.desc()).limit(limit)
        return (await self.session.execute(stmt)).scalars().all()

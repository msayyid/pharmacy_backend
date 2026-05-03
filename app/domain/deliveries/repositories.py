"""Delivery repository — write + read on the per-order handover record."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.deliveries.models import Delivery


class DeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_for_order(
        self,
        *,
        order_id: UUID,
        provider: str | None,
        courier_name: str | None,
        courier_phone: str | None,
        tracking_number: str | None = None,
        estimated_at: datetime | None = None,
        assigned_at: datetime | None = None,
        delivery_fee_actual: Decimal | None = None,
        notes: str | None = None,
    ) -> Delivery:
        row = Delivery(
            order_id=order_id,
            provider=provider,
            courier_name=courier_name,
            courier_phone=courier_phone,
            tracking_number=tracking_number,
            estimated_at=estimated_at,
            assigned_at=assigned_at,
            delivery_fee_actual=delivery_fee_actual,
            notes=notes,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_for_order(self, order_id: UUID) -> Delivery | None:
        stmt = select(Delivery).where(Delivery.order_id == order_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def mark_picked_up(self, order_id: UUID, *, at: datetime) -> None:
        row = await self.get_for_order(order_id)
        if row is None:
            return
        row.picked_up_at = at
        await self.session.flush()

    async def mark_delivered(
        self,
        order_id: UUID,
        *,
        at: datetime,
        delivery_fee_actual: Decimal | None = None,
    ) -> None:
        row = await self.get_for_order(order_id)
        if row is None:
            return
        row.delivered_at = at
        if delivery_fee_actual is not None:
            row.delivery_fee_actual = delivery_fee_actual
        await self.session.flush()

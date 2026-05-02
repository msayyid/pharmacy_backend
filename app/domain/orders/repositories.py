"""Orders domain — repositories.

* :class:`CartRepository` — get-or-create per user / per session,
  fetch with items, clear, prune-expired.
* :class:`OrderRepository` — load by id / by order_number with eager
  items + history, paginated user listing, append.
* :class:`OrderStatusHistoryRepository` — append-only.
* :class:`OrderSequenceRepository` — atomic per-year increment for
  ``order_number`` allocation.

Repositories are thin: queries shaped for intent, no business rules,
no commits, no Pydantic. Services own transactions.

Reference: BACKEND_BLUEPRINT.md §11; PHARMACY_BLUEPRINT_2.md §7, §11.4.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.types import uuid7
from app.domain.orders.models import (
    Cart,
    CartItem,
    Order,
    OrderSequence,
    OrderStatusHistory,
)

CART_TTL_DAYS = 30


# ─── Carts ────────────────────────────────────────────────────────────────────


class CartRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, cart_id: UUID) -> Cart | None:
        stmt = select(Cart).where(Cart.id == cart_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_with_items(self, cart_id: UUID) -> Cart | None:
        stmt = select(Cart).options(selectinload(Cart.items)).where(Cart.id == cart_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_user(self, user_id: UUID) -> Cart | None:
        """Most-recent non-expired cart for a user."""
        stmt = (
            select(Cart)
            .options(selectinload(Cart.items))
            .where(Cart.user_id == user_id)
            .order_by(Cart.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_session(self, session_id: str) -> Cart | None:
        stmt = (
            select(Cart)
            .options(selectinload(Cart.items))
            .where(Cart.session_id == session_id, Cart.user_id.is_(None))
            .order_by(Cart.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        branch_id: int,
        user_id: UUID | None = None,
        session_id: str | None = None,
        currency: str = "KGS",
    ) -> Cart:
        if user_id is None and session_id is None:
            msg = "Cart must have user_id or session_id"
            raise ValueError(msg)
        cart = Cart(
            id=uuid7(),
            user_id=user_id,
            session_id=session_id,
            branch_id=branch_id,
            currency=currency,
            expires_at=datetime.now(tz=UTC).replace(tzinfo=None) + timedelta(days=CART_TTL_DAYS),
        )
        self.session.add(cart)
        await self.session.flush()
        await self.session.refresh(cart)
        return cart

    async def clear_items(self, cart_id: UUID) -> int:
        """Delete all ``cart_items`` rows for a cart; preserves the cart row."""
        from sqlalchemy import delete as _delete

        stmt = _delete(CartItem).where(CartItem.cart_id == cart_id)
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def delete_expired(self, *, now: datetime | None = None) -> int:
        """Delete carts whose ``expires_at`` is in the past.

        Phase 11 schedules this; Phase 8 ships the method.
        """
        from sqlalchemy import delete as _delete

        cutoff = now or datetime.now(tz=UTC).replace(tzinfo=None)
        stmt = _delete(Cart).where(Cart.expires_at < cutoff)
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)  # type: ignore[attr-defined]


# ─── Orders ───────────────────────────────────────────────────────────────────


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, order: Order) -> None:
        self.session.add(order)
        await self.session.flush()

    async def get_by_id(self, order_id: UUID) -> Order | None:
        stmt = select(Order).where(Order.id == order_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_with_items(self, order_id: UUID) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.history))
            .where(Order.id == order_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_number_with_items(self, order_number: str) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.history))
            .where(Order.order_number == order_number)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user_paginated(
        self,
        *,
        user_id: UUID,
        offset: int = 0,
        limit: int = 24,
    ) -> tuple[Sequence[Order], int]:
        base = select(Order).where(Order.user_id == user_id)
        total_stmt = select(func.count()).select_from(base.subquery())
        items_stmt = (
            base.order_by(Order.created_at.desc(), Order.id.desc()).offset(offset).limit(limit)
        )
        total = (await self.session.execute(total_stmt)).scalar_one()
        items = (await self.session.execute(items_stmt)).scalars().all()
        return (items, total)


class OrderStatusHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self,
        *,
        order_id: UUID,
        from_status: str | None,
        to_status: str,
        changed_by_admin_id: int | None = None,
        changed_by_system: bool = False,
        notes: str | None = None,
    ) -> OrderStatusHistory:
        row = OrderStatusHistory(
            order_id=order_id,
            from_status=from_status,
            to_status=to_status,
            changed_by_admin_id=changed_by_admin_id,
            changed_by_system=changed_by_system,
            notes=notes,
        )
        self.session.add(row)
        await self.session.flush()
        return row


# ─── Order-number sequence ───────────────────────────────────────────────────


class OrderSequenceRepository:
    """Atomic per-year ``order_number`` counter.

    Locks the row with ``FOR UPDATE`` so concurrent place-orders
    serialise on the increment. The first call for a new year creates
    the row at ``last_assigned = 0``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_for_year(self, year: int) -> int:
        """Increment + return the next sequence value for ``year``."""
        stmt = select(OrderSequence).where(OrderSequence.year == year).with_for_update()
        seq = (await self.session.execute(stmt)).scalar_one_or_none()
        if seq is None:
            seq = OrderSequence(year=year, last_assigned=0)
            self.session.add(seq)
            await self.session.flush()
            # Re-lock the freshly-inserted row.
            seq = (await self.session.execute(stmt)).scalar_one()
        seq.last_assigned += 1
        await self.session.flush()
        return seq.last_assigned

    async def format_order_number(self, *, year: int) -> str:
        value = await self.next_for_year(year)
        return f"PH-{year}-{value:06d}"

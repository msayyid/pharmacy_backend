"""Admin order lifecycle — config-driven state-machine dispatcher.

The single source of truth is :data:`ALLOWED_TRANSITIONS`. Every
admin-driven status change funnels through :meth:`OrderLifecycleService.
dispatch`, which:

* validates the ``(from, to)`` pair is a real transition;
* validates the actor's role is in ``allowed_roles``;
* validates a ``reason`` is supplied when ``requires_reason=True``;
* runs the registered ``on_success`` hooks **inside the same DB
  transaction** (stock release / restock / convert reserved→sold /
  refund-row creation);
* writes one ``order_status_history`` row + one ``admin_audit_log``
  row per transition.

Hand-coded transition logic in ten places was rejected per CLAUDE.md.

Reference: PRODUCT_BLUEPRINT.md §9.1 (state machine), §17.2, §19.5
(role permissions); PHARMACY_BLUEPRINT_2.md §7.5 (status history).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.core.types import uuid7
from app.domain.identity.models import AdminUser
from app.domain.inventory.models import (
    MovementType,
    StockMovement,
)
from app.domain.inventory.repositories import (
    BranchProductRepository,
    InventoryBatchRepository,
    StockMovementRepository,
)
from app.domain.inventory.services import InventoryService
from app.domain.ops.services import AdminAuditLogService
from app.domain.orders.models import (
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.domain.orders.repositories import (
    OrderRepository,
    OrderStatusHistoryRepository,
)

# ─── Role constants ──────────────────────────────────────────────────────────


SUPER_ADMIN = "super_admin"
BRANCH_MANAGER = "branch_manager"
PHARMACIST = "pharmacist"
CONTENT_EDITOR = "content_editor"


# ─── Transition rule ─────────────────────────────────────────────────────────


HookContext = dict[str, Any]
"""Per-call context passed to side-effect hooks (kwargs from dispatch)."""


@dataclass(frozen=True)
class TransitionRule:
    """One row of the state-transition matrix."""

    allowed_roles: tuple[str, ...]
    on_success: tuple[
        Callable[
            [OrderLifecycleService, Order, AdminUser, HookContext],
            Awaitable[None],
        ],
        ...,
    ] = field(default_factory=tuple)
    requires_reason: bool = False


# ─── Side-effect hooks (used in ALLOWED_TRANSITIONS) ─────────────────────────


async def _release_reservations(
    svc: OrderLifecycleService,
    order: Order,
    actor: AdminUser,
    ctx: HookContext,
) -> None:
    await svc.inventory.release_reservations(order.id, actor=actor)


async def _convert_reservation_to_sold(
    svc: OrderLifecycleService,
    order: Order,
    actor: AdminUser,
    ctx: HookContext,
) -> None:
    await svc.inventory.convert_reservation_to_sold(order.id, actor=actor)


async def _restock_for_cancelled_dispatch(
    svc: OrderLifecycleService,
    order: Order,
    actor: AdminUser,
    ctx: HookContext,
) -> None:
    await svc.inventory.restock_for_cancelled_dispatch(order.id, actor=actor)


async def _record_courier(
    svc: OrderLifecycleService,
    order: Order,
    actor: AdminUser,
    ctx: HookContext,
) -> None:
    """Stash courier name + phone on the order (Phase 9 inline; Phase
    10 will move these to a ``deliveries`` row)."""
    courier_name = ctx.get("courier_name")
    courier_phone = ctx.get("courier_phone")
    if not courier_name or not courier_phone:
        raise ValidationError(code="courier_info_required")
    order.courier_name = courier_name
    order.courier_phone = courier_phone


async def _create_refund_payment_row(
    svc: OrderLifecycleService,
    order: Order,
    actor: AdminUser,
    ctx: HookContext,
) -> None:
    """COD refund = status flip only (no money to return). Card refund
    = create a pending ``Payment`` row with ``is_refund=True``; admin
    completes via gateway dashboard at MVP, Phase 10 wires the real
    refund call.
    """
    if order.payment_method != PaymentMethod.CARD_ONLINE.value:
        # COD path: nothing to do — order.payment_status flip is enough.
        order.payment_status = PaymentStatus.REFUNDED.value
        return
    amount: Decimal | None = ctx.get("amount")
    if amount is None or amount <= 0 or amount > order.total:
        raise ValidationError(
            code="invalid_refund_amount",
            amount=str(amount) if amount is not None else None,
            order_total=str(order.total),
        )
    refund = Payment(
        id=uuid7(),
        order_id=order.id,
        provider="freedom_pay",  # MVP single gateway
        amount=amount,
        currency=order.currency,
        status=PaymentStatus.PENDING.value,
        is_refund=True,
        failure_reason=None,
    )
    svc.session.add(refund)
    await svc.session.flush()
    # If the full order total is being refunded, mark the order
    # ``payment_status='refunded'``. Partials → ``partially_refunded``.
    if amount == order.total:
        order.payment_status = PaymentStatus.REFUNDED.value
    else:
        order.payment_status = PaymentStatus.PARTIALLY_REFUNDED.value


# ─── The transition matrix ───────────────────────────────────────────────────


_PHARMACY_ROLES = (SUPER_ADMIN, BRANCH_MANAGER, PHARMACIST)
_PRICING_ROLES = (SUPER_ADMIN, BRANCH_MANAGER)


ALLOWED_TRANSITIONS: dict[tuple[str, str], TransitionRule] = {
    ("pending", "confirmed"): TransitionRule(
        allowed_roles=_PHARMACY_ROLES,
    ),
    ("confirmed", "preparing"): TransitionRule(
        allowed_roles=_PHARMACY_ROLES,
    ),
    ("preparing", "ready_for_pickup"): TransitionRule(
        allowed_roles=_PHARMACY_ROLES,
        on_success=(_convert_reservation_to_sold,),
    ),
    ("preparing", "out_for_delivery"): TransitionRule(
        allowed_roles=_PHARMACY_ROLES,
        on_success=(_record_courier, _convert_reservation_to_sold),
    ),
    ("ready_for_pickup", "delivered"): TransitionRule(
        allowed_roles=_PHARMACY_ROLES,
    ),
    ("out_for_delivery", "delivered"): TransitionRule(
        allowed_roles=_PHARMACY_ROLES,
    ),
    ("pending", "cancelled"): TransitionRule(
        allowed_roles=_PHARMACY_ROLES,
        on_success=(_release_reservations,),
        requires_reason=True,
    ),
    ("confirmed", "cancelled"): TransitionRule(
        allowed_roles=_PHARMACY_ROLES,
        on_success=(_release_reservations,),
        requires_reason=True,
    ),
    ("preparing", "cancelled"): TransitionRule(
        allowed_roles=_PHARMACY_ROLES,
        on_success=(_release_reservations,),
        requires_reason=True,
    ),
    ("out_for_delivery", "cancelled"): TransitionRule(
        allowed_roles=_PHARMACY_ROLES,
        on_success=(_restock_for_cancelled_dispatch,),
        requires_reason=True,
    ),
    ("delivered", "refunded"): TransitionRule(
        allowed_roles=_PRICING_ROLES,
        on_success=(_create_refund_payment_row,),
        requires_reason=True,
    ),
}


# ─── Cancellation reasons (PRODUCT §9.1 + §17.2) ─────────────────────────────


CANCEL_REASONS = frozenset(
    {
        "customer_changed_mind",
        "out_of_stock_at_picking",
        "customer_unreachable",
        "customer_refused_at_door",
        "payment_failed",
        "auto_timeout_unconfirmed",
        "other",
    }
)


# ─── The service ─────────────────────────────────────────────────────────────


class OrderLifecycleService:
    """Admin-driven status transitions, batch swaps, and refunds."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        orders: OrderRepository,
        order_history: OrderStatusHistoryRepository,
        batches: InventoryBatchRepository,
        branch_products: BranchProductRepository,
        movements: StockMovementRepository,
        inventory: InventoryService,
        audit: AdminAuditLogService,
    ) -> None:
        self.session = session
        self.orders = orders
        self.order_history = order_history
        self.batches = batches
        self.branch_products = branch_products
        self.movements = movements
        self.inventory = inventory
        self.audit = audit

    # ─── Generic dispatcher ────────────────────────────────────────────────

    async def dispatch(
        self,
        *,
        order_id: UUID,
        to_status: str,
        actor: AdminUser,
        reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        **hook_kwargs: Any,
    ) -> Order:
        order = await self.orders.get_by_id_with_items(order_id)
        if order is None:
            raise NotFoundError(code="order_not_found", order_id=str(order_id))

        from_status = order.status
        rule = ALLOWED_TRANSITIONS.get((from_status, to_status))
        if rule is None:
            raise ConflictError(
                code="transition_not_allowed",
                from_status=from_status,
                to_status=to_status,
            )
        if actor.role not in rule.allowed_roles:
            raise PermissionDeniedError(
                code="forbidden_role",
                role=actor.role,
                allowed=list(rule.allowed_roles),
            )
        if rule.requires_reason and not reason:
            raise ValidationError(code="reason_required")
        if (
            rule.requires_reason
            and reason
            and to_status == "cancelled"
            and reason not in CANCEL_REASONS
        ):
            raise ValidationError(
                code="invalid_cancel_reason",
                reason=reason,
                allowed=sorted(CANCEL_REASONS),
            )

        before = _order_snapshot(order)
        # Per-branch RBAC: non-super admins can only act on their own branch.
        if (
            actor.role != SUPER_ADMIN
            and actor.branch_id is not None
            and order.branch_id != actor.branch_id
        ):
            raise PermissionDeniedError(
                code="forbidden_branch",
                admin_branch=actor.branch_id,
                target_branch=order.branch_id,
            )

        # Apply state change.
        order.status = to_status
        now = datetime.now(tz=UTC).replace(tzinfo=None)
        if to_status == OrderStatus.CONFIRMED.value:
            order.confirmed_at = now
        elif to_status == OrderStatus.DELIVERED.value:
            order.delivered_at = now
        elif to_status in (OrderStatus.CANCELLED.value, OrderStatus.REFUNDED.value):
            order.cancelled_at = now
            if reason is not None:
                order.cancel_reason = reason

        # Run side-effect hooks in this transaction.
        ctx: HookContext = {"reason": reason, **hook_kwargs}
        for hook in rule.on_success:
            await hook(self, order, actor, ctx)

        # Status history row.
        await self.order_history.append(
            order_id=order.id,
            from_status=from_status,
            to_status=to_status,
            changed_by_admin_id=actor.id,
            changed_by_system=False,
            notes=reason,
        )

        # Audit row.
        await self.audit.record(
            admin_user_id=actor.id,
            action=f"order.{to_status}",
            entity_type="order",
            entity_id=str(order.id),
            before=before,
            after=_order_snapshot(order),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self.session.flush()
        return order

    # ─── Public lifecycle methods (thin wrappers around dispatch) ──────────

    async def confirm(
        self,
        order_id: UUID,
        *,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Order:
        return await self.dispatch(
            order_id=order_id,
            to_status=OrderStatus.CONFIRMED.value,
            actor=actor,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def start_preparing(
        self,
        order_id: UUID,
        *,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Order:
        return await self.dispatch(
            order_id=order_id,
            to_status=OrderStatus.PREPARING.value,
            actor=actor,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def mark_ready_for_pickup(
        self,
        order_id: UUID,
        *,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Order:
        return await self.dispatch(
            order_id=order_id,
            to_status=OrderStatus.READY_FOR_PICKUP.value,
            actor=actor,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def mark_out_for_delivery(
        self,
        order_id: UUID,
        *,
        actor: AdminUser,
        courier_name: str,
        courier_phone: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Order:
        return await self.dispatch(
            order_id=order_id,
            to_status=OrderStatus.OUT_FOR_DELIVERY.value,
            actor=actor,
            courier_name=courier_name,
            courier_phone=courier_phone,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def mark_delivered(
        self,
        order_id: UUID,
        *,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Order:
        return await self.dispatch(
            order_id=order_id,
            to_status=OrderStatus.DELIVERED.value,
            actor=actor,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def cancel_by_admin(
        self,
        order_id: UUID,
        *,
        actor: AdminUser,
        reason: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Order:
        return await self.dispatch(
            order_id=order_id,
            to_status=OrderStatus.CANCELLED.value,
            actor=actor,
            reason=reason,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def refund(
        self,
        order_id: UUID,
        *,
        actor: AdminUser,
        amount: Decimal,
        reason: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Order:
        return await self.dispatch(
            order_id=order_id,
            to_status=OrderStatus.REFUNDED.value,
            actor=actor,
            reason=reason,
            amount=amount,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    # ─── Batch swap (mid-picking; not a state transition) ─────────────────

    async def swap_batch(
        self,
        *,
        order_id: UUID,
        item_id: int,
        new_batch_id: int,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> OrderItem:
        """Pharmacist replaces one batch with a different batch of the
        **same product** during picking. Writes paired ``released``
        (old batch) + ``reserved`` (new batch) movements + updates the
        ``OrderItem`` snapshots.
        """
        order = await self.orders.get_by_id_with_items(order_id)
        if order is None:
            raise NotFoundError(code="order_not_found", order_id=str(order_id))
        if order.status not in (
            OrderStatus.CONFIRMED.value,
            OrderStatus.PREPARING.value,
        ):
            raise ConflictError(code="swap_not_allowed_in_status", status=order.status)
        # Per-branch RBAC.
        if (
            actor.role != SUPER_ADMIN
            and actor.branch_id is not None
            and order.branch_id != actor.branch_id
        ):
            raise PermissionDeniedError(code="forbidden_branch")

        # Locate the order_item.
        item: OrderItem | None = next((it for it in order.items if it.id == item_id), None)
        if item is None:
            raise NotFoundError(code="order_item_not_found", item_id=item_id)
        if item.inventory_batch_id is None:
            raise ConflictError(code="order_item_has_no_batch", item_id=item_id)

        old_batch = await self.batches.get_by_id(item.inventory_batch_id)
        new_batch = await self.batches.get_by_id(new_batch_id)
        if old_batch is None or new_batch is None:
            raise NotFoundError(code="batch_not_found")
        if new_batch.product_id != item.product_id:
            raise ValidationError(code="batch_product_mismatch")
        if new_batch.branch_id != order.branch_id:
            raise ValidationError(code="batch_branch_mismatch")
        if new_batch.quantity_remaining - new_batch.quantity_reserved < item.quantity:
            raise ConflictError(
                code="new_batch_insufficient_stock",
                requested=item.quantity,
                available=new_batch.quantity_remaining - new_batch.quantity_reserved,
            )

        before = _item_snapshot(item)

        # Release on the old batch.
        old_batch.quantity_reserved -= item.quantity
        await self.movements.append(
            StockMovement(
                inventory_batch_id=old_batch.id,
                branch_id=order.branch_id,
                product_id=item.product_id,
                movement_type=MovementType.RELEASED.value,
                quantity_change=item.quantity,
                quantity_after=old_batch.quantity_remaining,
                order_id=order.id,
                admin_user_id=actor.id,
                reason="batch_swap_release",
            )
        )

        # Reserve on the new batch.
        new_batch.quantity_reserved += item.quantity
        await self.movements.append(
            StockMovement(
                inventory_batch_id=new_batch.id,
                branch_id=order.branch_id,
                product_id=item.product_id,
                movement_type=MovementType.RESERVED.value,
                quantity_change=-item.quantity,
                quantity_after=new_batch.quantity_remaining,
                order_id=order.id,
                admin_user_id=actor.id,
                reason="batch_swap_reserve",
            )
        )

        # Update the order_item snapshot.
        item.inventory_batch_id = new_batch.id
        item.batch_number_snapshot = new_batch.batch_number
        item.expiry_date_snapshot = new_batch.expiry_date

        await self.audit.record(
            admin_user_id=actor.id,
            action="order_item.swap_batch",
            entity_type="order_item",
            entity_id=str(item.id),
            before=before,
            after=_item_snapshot(item),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self.session.flush()
        return item


# ─── Snapshot helpers ────────────────────────────────────────────────────────


def _order_snapshot(o: Order) -> dict[str, Any]:
    return {
        "status": o.status,
        "payment_status": o.payment_status,
        "courier_name": o.courier_name,
        "courier_phone": o.courier_phone,
        "cancel_reason": o.cancel_reason,
    }


def _item_snapshot(it: OrderItem) -> dict[str, Any]:
    return {
        "inventory_batch_id": it.inventory_batch_id,
        "batch_number_snapshot": it.batch_number_snapshot,
        "expiry_date_snapshot": (
            it.expiry_date_snapshot.isoformat() if it.expiry_date_snapshot is not None else None
        ),
        "quantity": it.quantity,
    }

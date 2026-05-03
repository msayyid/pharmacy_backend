"""PaymentService — webhook handling + payment row helpers.

The webhook handler is the inbound bridge from the gateway: signature
already verified upstream by the route, this method finds the matching
``Payment`` row by ``provider_transaction_id`` and applies the event:

* ``charge_succeeded`` → flip Payment to ``paid``, set ``paid_at``,
  flip ``Order.payment_status`` to ``paid`` for the matching order.
* ``charge_failed`` → flip Payment to ``failed`` + record failure_reason.
* ``refund_succeeded`` → flip the matching refund Payment to ``paid``,
  flip ``Order.payment_status`` to ``refunded`` (or
  ``partially_refunded`` if not full).
* ``refund_failed`` → flip refund Payment to ``failed``.

Idempotency: dedupe on ``(provider, event_id)`` via Redis ``SETNX`` with
24h TTL — a redelivered webhook is a no-op rather than a double-flip.
The TTL is long enough to cover gateway retries; a true Long Idle
window (multi-day outage) is out of scope.

Reference: PRODUCT §11.5, §17.6; PHARMACY §7.6.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.types import uuid7
from app.domain.orders.models import (
    Order,
    Payment,
    PaymentStatus,
)
from app.integrations.payments.base import ParsedEvent

log = get_logger(__name__)


WEBHOOK_DEDUPE_TTL_SECONDS = 24 * 60 * 60


WebhookDedupeCheck = Callable[[str], Awaitable[bool]]
"""Async callable: takes a dedupe key, returns True iff this is the
first time the key was seen (Redis ``SETNX`` semantics)."""


@dataclass(frozen=True, slots=True)
class WebhookOutcome:
    status: str  # 'applied' | 'duplicate' | 'no_match'
    payment_id: UUID | None


def _dedupe_key(provider: str, event_id: str) -> str:
    return f"v1:webhook:{provider}:{event_id}"


def _utc_naive() -> datetime:
    return datetime.now(tz=UTC).replace(tzinfo=None)


class PaymentService:
    """Webhook handling + initial-charge Payment row creation."""

    def __init__(self, *, session: AsyncSession) -> None:
        self.session = session

    # ─── Initial charge (called from CheckoutService.place_order) ──────────

    async def record_charge_initiated(
        self,
        *,
        order_id: UUID,
        provider: str,
        provider_transaction_id: str,
        amount: Decimal,
        currency: str,
        raw_response: dict[str, Any] | None = None,
    ) -> Payment:
        """Insert a ``pending`` Payment row right after ``create_intent``.

        The webhook will flip its status to ``paid`` (or ``failed``).
        """
        payment = Payment(
            id=uuid7(),
            order_id=order_id,
            provider=provider,
            provider_transaction_id=provider_transaction_id,
            amount=amount,
            currency=currency,
            status=PaymentStatus.PENDING.value,
            is_refund=False,
            raw_response=raw_response,
        )
        self.session.add(payment)
        await self.session.flush()
        return payment

    # ─── Webhook handler ──────────────────────────────────────────────────

    async def handle_webhook(
        self,
        event: ParsedEvent,
        *,
        provider: str,
        dedupe_check: WebhookDedupeCheck | None = None,
    ) -> WebhookOutcome:
        """Apply a parsed webhook event idempotently.

        Returns :class:`WebhookOutcome` describing what happened so the
        route can log it (``"applied"`` / ``"duplicate"`` / ``"no_match"``).
        """
        if dedupe_check is not None:
            is_first = await dedupe_check(_dedupe_key(provider, event.event_id))
            if not is_first:
                log.info(
                    "webhook_duplicate",
                    provider=provider,
                    event_id=event.event_id,
                    event_type=event.event_type,
                )
                return WebhookOutcome(status="duplicate", payment_id=None)

        # Find the Payment row by provider_transaction_id. For refunds
        # that came from our own ``lifecycle.refund``, the row is
        # already there with ``is_refund=True``. For charges from
        # ``record_charge_initiated``, same lookup, ``is_refund=False``.
        stmt = select(Payment).where(
            Payment.provider == provider,
            Payment.provider_transaction_id == event.provider_transaction_id,
            Payment.is_refund == event.is_refund,
        )
        payment = (await self.session.execute(stmt)).scalars().first()
        if payment is None:
            log.warning(
                "webhook_no_match",
                provider=provider,
                event_id=event.event_id,
                provider_transaction_id=event.provider_transaction_id,
            )
            return WebhookOutcome(status="no_match", payment_id=None)

        order = await self.session.get(Order, payment.order_id)
        if order is None:
            log.warning(
                "webhook_order_missing",
                payment_id=str(payment.id),
                order_id=str(payment.order_id),
            )
            return WebhookOutcome(status="no_match", payment_id=payment.id)

        if event.event_type == "charge_succeeded":
            payment.status = PaymentStatus.PAID.value
            payment.paid_at = _utc_naive()
            order.payment_status = PaymentStatus.PAID.value
        elif event.event_type == "charge_failed":
            payment.status = PaymentStatus.FAILED.value
            payment.failure_reason = event.failure_reason
            order.payment_status = PaymentStatus.FAILED.value
        elif event.event_type == "refund_succeeded":
            payment.status = PaymentStatus.PAID.value  # the refund itself succeeded
            payment.paid_at = _utc_naive()
            order.payment_status = (
                PaymentStatus.REFUNDED.value
                if event.amount == order.total
                else PaymentStatus.PARTIALLY_REFUNDED.value
            )
        elif event.event_type == "refund_failed":
            payment.status = PaymentStatus.FAILED.value
            payment.failure_reason = event.failure_reason

        await self.session.flush()
        log.info(
            "webhook_applied",
            provider=provider,
            event_id=event.event_id,
            event_type=event.event_type,
            payment_id=str(payment.id),
            order_id=str(order.id),
        )
        return WebhookOutcome(status="applied", payment_id=payment.id)

    # ─── Refund initiator (called from OrderLifecycleService.refund) ──────

    async def record_refund_initiated(
        self,
        *,
        order_id: UUID,
        provider: str,
        provider_transaction_id: str | None,
        amount: Decimal,
        currency: str,
    ) -> Payment:
        """Insert a ``pending`` refund Payment row.

        For COD orders, ``provider_transaction_id`` is None — the row
        is informational and Phase 12 reconciliation handles physical
        cash. For card orders, the gateway's refund_id (returned by
        ``client.refund``) is stored here; the webhook then flips it to
        ``paid``.
        """
        refund = Payment(
            id=uuid7(),
            order_id=order_id,
            provider=provider,
            provider_transaction_id=provider_transaction_id,
            amount=amount,
            currency=currency,
            status=PaymentStatus.PENDING.value,
            is_refund=True,
        )
        self.session.add(refund)
        await self.session.flush()
        return refund

"""Payment client Protocol + value types.

Three operations the gateway integration covers:

* :meth:`PaymentClient.create_intent` — mint a hosted-checkout URL the
  customer is redirected to. Returns ``redirect_url`` + the gateway's
  own transaction id (we store it as ``Payment.provider_transaction_id``).
* :meth:`PaymentClient.refund` — call the gateway to refund a previously
  successful charge. Returns the gateway's refund id.
* :meth:`PaymentClient.verify_webhook` — given the raw body + signature
  header, confirm the event is genuinely from the gateway and parse it.
  Returns a :class:`ParsedEvent`. Raises :class:`InvalidSignatureError`
  on signature mismatch.

Phase 10 ships :class:`FakePaymentClient` for tests and dev, plus a
scaffolded :class:`FreedomPayClient` whose calls raise
``NotImplementedError`` pending vendor-doc verification (OPEN_QUESTIONS
Q14).

Reference: PRODUCT §11.5, §17.6; PHARMACY §7.6; BACKEND §10.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

from app.core.errors import AppError


class InvalidSignatureError(AppError):
    """Webhook signature didn't verify — request is rejected with 400."""

    code = "invalid_signature"
    status_code = 400


@dataclass(frozen=True, slots=True)
class CreateIntentResult:
    """Outcome of :meth:`PaymentClient.create_intent`."""

    redirect_url: str
    provider_transaction_id: str
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RefundResult:
    """Outcome of :meth:`PaymentClient.refund`."""

    refund_id: str
    raw: dict[str, Any] | None = None


EventType = Literal["charge_succeeded", "charge_failed", "refund_succeeded", "refund_failed"]


@dataclass(frozen=True, slots=True)
class ParsedEvent:
    """Provider-agnostic webhook event."""

    event_id: str
    event_type: EventType
    provider_transaction_id: str
    amount: Decimal
    currency: str
    is_refund: bool
    failure_reason: str | None = None
    raw: dict[str, Any] | None = None


class PaymentClient(Protocol):
    """The contract every payment gateway adapter implements."""

    provider: str

    async def create_intent(
        self,
        *,
        order_id: str,
        order_number: str,
        amount: Decimal,
        currency: str,
        recipient_phone: str,
        return_url: str,
    ) -> CreateIntentResult: ...

    async def refund(
        self,
        *,
        provider_transaction_id: str,
        amount: Decimal,
        reason: str | None = None,
    ) -> RefundResult: ...

    async def verify_webhook(
        self,
        *,
        body: bytes,
        signature: str | None,
    ) -> ParsedEvent: ...

    async def verify_status(
        self,
        *,
        provider_transaction_id: str,
    ) -> ParsedEvent | None:
        """Look up the gateway-side status for a transaction.

        Used by the hourly :func:`payment_reconcile` worker to catch
        webhooks that never arrived. Returns a :class:`ParsedEvent` if
        the gateway has a definitive answer (paid / failed); ``None``
        if the transaction is still pending or unknown.
        """
        ...

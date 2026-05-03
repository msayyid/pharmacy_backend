"""Fake payment client for tests + dev.

* :meth:`create_intent` returns a deterministic redirect URL + a
  stable provider txn id derived from ``order_id``. Every call is
  recorded in :attr:`intents`.
* :meth:`refund` records the call and returns a synthetic ``refund_id``.
* :meth:`verify_webhook` parses our own JSON test format (no
  signature crypto) and trusts the ``signature`` argument equals
  :attr:`signing_token` — anything else raises
  :class:`InvalidSignatureError`. Tests build payloads via
  :meth:`make_event_payload`.

Together this lets the e2e flow (place card order → POST webhook →
order flips) run without any real gateway involvement.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.core.logging import get_logger
from app.integrations.payments.base import (
    CreateIntentResult,
    EventType,
    InvalidSignatureError,
    ParsedEvent,
    RefundResult,
)

log = get_logger(__name__)


class FakePaymentClient:
    """In-process fake. Records every call; deterministic outputs."""

    provider: str = "fake"

    def __init__(self, *, signing_token: str = "fake-signing-token") -> None:  # noqa: S107 — fake test client; literally a placeholder, never sees prod traffic.
        self.signing_token = signing_token
        self.intents: list[dict[str, Any]] = []
        self.refunds: list[dict[str, Any]] = []

    async def create_intent(
        self,
        *,
        order_id: str,
        order_number: str,
        amount: Decimal,
        currency: str,
        recipient_phone: str,
        return_url: str,
    ) -> CreateIntentResult:
        txn = f"fake-txn-{order_id[:8]}"
        self.intents.append(
            {
                "order_id": order_id,
                "order_number": order_number,
                "amount": str(amount),
                "currency": currency,
                "recipient_phone": recipient_phone,
                "txn": txn,
            }
        )
        log.info(
            "payment_intent_created_fake",
            order_number=order_number,
            amount=str(amount),
            txn=txn,
        )
        return CreateIntentResult(
            redirect_url=f"https://payments.fake/pay/{txn}",
            provider_transaction_id=txn,
            raw={"provider": self.provider, "ok": True},
        )

    async def refund(
        self,
        *,
        provider_transaction_id: str,
        amount: Decimal,
        reason: str | None = None,
    ) -> RefundResult:
        refund_id = f"fake-refund-{uuid4().hex[:12]}"
        self.refunds.append(
            {
                "provider_transaction_id": provider_transaction_id,
                "amount": str(amount),
                "reason": reason,
                "refund_id": refund_id,
            }
        )
        log.info(
            "payment_refund_fake",
            provider_transaction_id=provider_transaction_id,
            refund_id=refund_id,
        )
        return RefundResult(
            refund_id=refund_id,
            raw={"provider": self.provider, "ok": True},
        )

    async def verify_webhook(
        self,
        *,
        body: bytes,
        signature: str | None,
    ) -> ParsedEvent:
        expected = hmac.new(
            self.signing_token.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if signature is None or not hmac.compare_digest(signature, expected):
            raise InvalidSignatureError(
                code="invalid_signature",
                provider=self.provider,
            )
        payload = json.loads(body)
        return ParsedEvent(
            event_id=str(payload["event_id"]),
            event_type=payload["event_type"],
            provider_transaction_id=str(payload["provider_transaction_id"]),
            amount=Decimal(str(payload["amount"])),
            currency=str(payload.get("currency", "KGS")),
            is_refund=payload["event_type"].startswith("refund_"),
            failure_reason=payload.get("failure_reason"),
            raw=payload,
        )

    # ─── Test helpers ──────────────────────────────────────────────────────

    @staticmethod
    def make_event_payload(
        *,
        provider_transaction_id: str,
        amount: Decimal,
        event_type: EventType = "charge_succeeded",
        currency: str = "KGS",
        failure_reason: str | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Build a webhook body the test will sign + POST."""
        return {
            "event_id": event_id or f"evt-{uuid4().hex}",
            "event_type": event_type,
            "provider_transaction_id": provider_transaction_id,
            "amount": str(amount),
            "currency": currency,
            "failure_reason": failure_reason,
        }

    def sign(self, body: bytes) -> str:
        """Compute the signature header for a body the test built."""
        return hmac.new(self.signing_token.encode(), body, hashlib.sha256).hexdigest()

    def reset(self) -> None:
        self.intents.clear()
        self.refunds.clear()


# Re-export the UUID helper so the route can pass it as ``order_id``
# regardless of whether tests give us str or UUID.
def _uuid_to_str(value: UUID | str) -> str:
    return str(value)


__all__ = ["FakePaymentClient"]

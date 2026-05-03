"""Freedom Pay (KG) real adapter — SCAFFOLD ONLY.

Endpoint URL, signature algorithm, request/response envelope, refund
endpoint, and webhook payload shape are **not yet vendor-verified**
(see OPEN_QUESTIONS Q14). The adapter compiles, type-checks, and is
wired through the factory, but each method raises
``NotImplementedError`` so it cannot silently ship a fabricated
request. The Phase 10 prompt explicitly flags the signature algorithm
as the make-or-break detail; we will not guess.

When vendor docs are obtained:

1. Confirm sandbox / production URLs against the current Freedom Pay
   developer portal.
2. Confirm signature algorithm (md5 / hmac-sha256?), field-ordering
   rule, and where in the request the signature lives.
3. Confirm amount unit (KGS decimal vs kopecks integer) and currency
   code form (``KGS`` vs ``417``).
4. Confirm webhook event-id field name (used for Redis SETNX dedupe).
5. Implement each method with httpx + tenacity (retry only on 5xx /
   network).
6. Add a unit test against captured request fixtures (``respx``).
7. Drop the ``NotImplementedError`` calls; close OPEN_QUESTIONS Q14.

Reference: PRODUCT §11.5, §17.6; PHARMACY §7.6.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.payments.base import (
    CreateIntentResult,
    ParsedEvent,
    PaymentClient,
    RefundResult,
)

_RETRYABLE: tuple[type[BaseException], ...] = (
    httpx.TransportError,
    httpx.HTTPStatusError,
)


class FreedomPayError(AppError):
    code = "payment_provider_error"
    status_code = 502


class FreedomPayClient:
    """Freedom Pay (KG) — body raises NotImplementedError pending vendor docs."""

    provider: str = "freedom_pay"

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        if settings.payment_api_url is None or settings.payment_merchant_id is None:
            raise FreedomPayError(
                code="payment_provider_misconfigured",
                detail="settings.payment_api_url + payment_merchant_id required",
            )
        self._settings = settings
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(15.0))
        self._endpoint = str(settings.payment_api_url).rstrip("/")
        self._merchant_id = settings.payment_merchant_id
        # Read-once: ``payment_secret`` is a SecretStr; the real adapter
        # will use it during signature build.

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
        """SCAFFOLD — see OPEN_QUESTIONS Q14."""
        async for attempt in AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.3, jitter=0.5, max=5.0),
            retry=retry_if_exception_type(_RETRYABLE),
        ):
            with attempt:
                raise NotImplementedError(
                    "FreedomPayClient.create_intent is unverified scaffold — see "
                    "OPEN_QUESTIONS Q14. Use payment_provider='fake' until the "
                    "Freedom Pay (KG) signature algorithm is vendor-verified."
                )
        raise AssertionError("unreachable")  # pragma: no cover

    async def refund(
        self,
        *,
        provider_transaction_id: str,
        amount: Decimal,
        reason: str | None = None,
    ) -> RefundResult:
        """SCAFFOLD — see OPEN_QUESTIONS Q14."""
        raise NotImplementedError(
            "FreedomPayClient.refund is unverified scaffold — see OPEN_QUESTIONS Q14."
        )

    async def verify_webhook(
        self,
        *,
        body: bytes,
        signature: str | None,
    ) -> ParsedEvent:
        """SCAFFOLD — see OPEN_QUESTIONS Q14.

        Webhook signature verification is mandatory; never trust an
        unsigned event. Implementation must reject 400 on mismatch.
        """
        raise NotImplementedError(
            "FreedomPayClient.verify_webhook is unverified scaffold — see " "OPEN_QUESTIONS Q14."
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ─── Signature helper (placeholder) ────────────────────────────────────

    def _sign(self, fields: dict[str, Any]) -> str:
        """Compute the request signature.

        SCAFFOLD: the real algorithm (likely md5 over alphabetically
        sorted ``key=value`` joined by Freedom Pay's secret) must be
        confirmed against vendor docs before any production call.
        """
        raise NotImplementedError(
            "FreedomPayClient._sign is unverified scaffold — see OPEN_QUESTIONS Q14."
        )


__all__ = ["FreedomPayClient", "FreedomPayError", "PaymentClient"]

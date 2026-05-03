"""Freedom Pay webhook receiver.

Pattern (PRODUCT §11.5, §17.6):

1. Read raw body + signature header.
2. ``client.verify_webhook(body, signature)`` — raises
   :class:`InvalidSignatureError` (400) if signature mismatches.
3. ``PaymentService.handle_webhook(event)`` — applies the event
   idempotently (Redis ``SETNX`` dedupe on ``event_id``).
4. Return ``200`` regardless of ``"applied"`` / ``"duplicate"`` /
   ``"no_match"`` — the gateway only retries on non-2xx, and a missing
   Payment row is a programming error worth investigating offline,
   not a transient retry.

The route uses the **fake** payment client by default so the e2e
"place card → POST webhook → order flips" flow runs in tests without
a real Freedom Pay sandbox.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.api.deps import DbSession, get_payment_client, get_payment_service
from app.core.redis import get_redis
from app.domain.payments.services import (
    WEBHOOK_DEDUPE_TTL_SECONDS,
    PaymentService,
    WebhookDedupeCheck,
)
from app.integrations.payments.base import PaymentClient

router = APIRouter(prefix="/webhooks/payments", tags=["webhooks"])


def _redis_setnx_dedupe_factory() -> WebhookDedupeCheck:
    """Build a `WebhookDedupeCheck` closure over the shared Redis client.

    Returns True iff this dedupe key was unseen — Redis ``SETNX`` semantics.
    Best-effort: if Redis isn't initialised (unit tests without Redis),
    treats every event as "first seen" so the handler still applies it.
    """

    async def _check(key: str) -> bool:
        try:
            redis = get_redis()
        except RuntimeError:
            return True
        # ``set(..., nx=True, ex=...)`` returns True iff the key was
        # set; subsequent calls with the same key return False.
        result = await redis.set(key, "1", nx=True, ex=WEBHOOK_DEDUPE_TTL_SECONDS)
        return bool(result)

    return _check


@router.post("/freedom-pay", status_code=200)
async def freedom_pay_webhook(
    request: Request,
    session: DbSession,
    payment_service: Annotated[PaymentService, Depends(get_payment_service)],
    client: Annotated[PaymentClient, Depends(get_payment_client)],
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
) -> dict[str, str]:
    body = await request.body()
    event = await client.verify_webhook(body=body, signature=x_signature)
    outcome = await payment_service.handle_webhook(
        event,
        provider=client.provider,
        dedupe_check=_redis_setnx_dedupe_factory(),
    )
    return {"status": outcome.status, "event_id": event.event_id}

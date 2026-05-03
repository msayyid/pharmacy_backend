"""ARQ ``send_sms`` worker function — Phase 10 ships the body.

Registration on :class:`app.workers.settings.WorkerSettings.functions`
lands in Phase 11 alongside the rest of the worker scheduling.

Pattern (BACKEND §17.3):

* Open a fresh session via :func:`session_scope` — never pass a session
  through ``ctx``.
* Call the configured :class:`SmsClient` (Nikita real, or fake).
* On success: ``mark_sent`` with the provider message id + cost.
* On failure: ``mark_failed`` and re-raise so ARQ retries per
  ``max_tries`` with exponential backoff.

The job arguments are JSON-serialisable (no ORM models, no
``datetime``-with-tz).
"""

from __future__ import annotations

from typing import Any

from app.core.db import session_scope
from app.core.logging import get_logger
from app.domain.ops.repositories import SmsLogRepository
from app.integrations.sms.factory import get_sms_client

log = get_logger(__name__)


async def send_sms(
    ctx: dict[str, Any],
    *,
    sms_log_id: int,
    phone: str,
    body: str,
    purpose: str,
) -> str | None:
    """Deliver one SMS and reconcile the ``sms_log`` row.

    Re-running with the same ``sms_log_id`` is *not* idempotent at the
    provider level — Nikita dedupes on its own ``<id>`` field, not ours
    — but it IS safe at the DB level: the row's ``status`` is the only
    thing that changes. Phase 12 hardens with provider-side dedupe once
    the Nikita ``<id>`` field is verified.
    """
    client = get_sms_client()
    try:
        result = await client.send(phone=phone, body=body)
    except Exception as exc:
        log.warning("sms_send_failed", purpose=purpose, error=str(exc))
        async with session_scope() as session:
            await SmsLogRepository(session).mark_failed(sms_log_id, error=str(exc))
        raise

    async with session_scope() as session:
        await SmsLogRepository(session).mark_sent(
            sms_log_id,
            provider_message_id=result.message_id,
            cost=result.cost,
        )
    log.info(
        "sms_sent",
        purpose=purpose,
        provider=client.provider,
        provider_message_id=result.message_id,
    )
    return result.message_id

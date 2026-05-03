"""SMS — message shape, queue + client protocols, module-level singleton.

The abstraction here is **two-layered** (DECISION_LOG'd in Phase 10):

1. :class:`SmsQueue` — what services call. ``enqueue(message)`` records
   the intent (writes the ``sms_log`` row, hands work to the worker).
   This is the only thing services touch.

2. :class:`SmsClient` — what the worker calls to actually deliver.
   ``send(phone, body)`` returns a :class:`SendResult`. The fake client
   pretends to send; the real client (Phase 12 readiness) talks to
   Nikita SMSPRO.

Phase 10 ships :class:`FakeSmsQueue` + :class:`FakeSmsClient` for tests
and dev. The Nikita real client is scaffolded but raises
``NotImplementedError`` pending vendor-doc verification — see
``OPEN_QUESTIONS.md`` Q13. Phase 11 swaps :class:`FakeSmsQueue` for an
ARQ-backed queue that enqueues a job; the worker function lives in
:mod:`app.workers.sms`.

Reference: BACKEND_BLUEPRINT.md §10, §17.3; PRODUCT §14, §21.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SmsMessage:
    """An SMS to be delivered."""

    phone: str  # E.164
    body: str
    purpose: str  # 'otp' | 'order_placed' | 'order_confirmed' | ...


@dataclass(frozen=True, slots=True)
class SendResult:
    """Provider acknowledgement after a successful :meth:`SmsClient.send`."""

    message_id: str | None
    cost: Decimal | None = None
    raw: dict[str, object] | None = None


class SmsQueue(Protocol):
    """Queue an SMS for asynchronous delivery (services-facing API)."""

    async def enqueue(self, message: SmsMessage) -> None: ...


class SmsClient(Protocol):
    """Send an SMS via the configured provider (worker-facing API)."""

    provider: str

    async def send(self, *, phone: str, body: str) -> SendResult: ...


# ─── Module-level singleton ───────────────────────────────────────────────────

_default_queue: SmsQueue | None = None


def get_sms_queue() -> SmsQueue:
    """Return the active SMS queue. Lazily constructs a :class:`FakeSmsQueue`."""
    global _default_queue  # noqa: PLW0603 — module-level singleton
    if _default_queue is None:
        from app.integrations.sms.fake import FakeSmsQueue

        _default_queue = FakeSmsQueue()
    return _default_queue


def set_sms_queue(queue: SmsQueue | None) -> None:
    """Override the active SMS queue. Tests use this to inject a fresh fake."""
    global _default_queue  # noqa: PLW0603 — module-level singleton
    _default_queue = queue

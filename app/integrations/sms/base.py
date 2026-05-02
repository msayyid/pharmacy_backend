"""SMS — message shape, queue protocol, factory.

Phase 4 ships only the :class:`FakeSmsQueue` (in-process, logs to structlog
and stores enqueued messages for tests). Phase 11 will wire a real ARQ
queue. Phase 10 lands the real Nikita SMS adapter that the worker invokes.

The abstraction here is the **queue**, not the **client**. Services don't
send SMS directly — they enqueue. The worker pulls from the queue and
calls the adapter.

Reference: BACKEND_BLUEPRINT.md §17, §10 (integrations layer); PRODUCT
§14 (SMS strategy); CLAUDE_CODE_PROMPTS Phase 4 implementation guidance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SmsMessage:
    """An SMS to be delivered."""

    phone: str  # E.164
    body: str
    purpose: str  # 'otp' | 'order_placed' | 'order_confirmed' | ...


class SmsQueue(Protocol):
    """Queue an SMS for asynchronous delivery."""

    async def enqueue(self, message: SmsMessage) -> None: ...


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

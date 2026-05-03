"""In-process SMS queue + fake client.

* :class:`FakeSmsQueue` — services-facing fake. Stores every enqueued
  message in :attr:`sent` AND, when constructed with a session factory,
  writes one ``sms_log`` row per enqueue (status='queued'). Tests can
  assert against either surface.
* :class:`FakeSmsClient` — worker-facing fake. ``send`` returns a
  deterministic :class:`SendResult` and records each call in
  :attr:`calls`.

The structured log line carries the OTP body so the curl smoke recipe in
``BUILD_PROGRESS.md`` can read the code from ``make dev`` output. Phone
numbers are masked by the structlog ``redact_pii`` processor.

Reference: BACKEND_BLUEPRINT.md §10; PRODUCT_BLUEPRINT.md §14.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from decimal import Decimal
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.integrations.sms.base import SendResult, SmsMessage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)


SessionFactory = Callable[[], "AsyncIterator[AsyncSession]"]


class FakeSmsQueue:
    """In-process SMS queue. Stores every enqueued message in :attr:`sent`.

    When a ``session_factory`` is supplied, also writes one ``sms_log``
    row per enqueue (status='queued'). Phase 11 will replace this with
    an ARQ-backed queue that enqueues a job; the worker writes the
    sms_log row instead of the queue.
    """

    def __init__(self, *, session_factory: SessionFactory | None = None) -> None:
        self.sent: list[SmsMessage] = []
        self._session_factory = session_factory

    async def enqueue(self, message: SmsMessage) -> None:
        self.sent.append(message)
        log.info(
            "sms_enqueued",
            purpose=message.purpose,
            phone=message.phone,
            body=message.body,
        )
        if self._session_factory is None:
            return
        # Best-effort sms_log write. Failures here must not break the
        # caller; the in-memory record is still authoritative for tests.
        with suppress(Exception):
            await self._write_sms_log(message)

    async def _write_sms_log(self, message: SmsMessage) -> None:
        from app.domain.ops.repositories import SmsLogRepository

        async for session in self._session_factory():  # type: ignore[misc]
            repo = SmsLogRepository(session)
            await repo.create_queued(
                phone=message.phone,
                body=message.body,
                purpose=message.purpose,
                provider="fake",
            )
            await session.commit()
            return

    def reset(self) -> None:
        """Clear the in-memory log. Tests call this between scenarios."""
        self.sent.clear()


class FakeSmsClient:
    """Worker-facing fake. ``send`` succeeds deterministically and records the call."""

    provider: str = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def send(self, *, phone: str, body: str) -> SendResult:
        self.calls.append((phone, body))
        log.info("sms_sent_fake", phone=phone, body=body)
        return SendResult(
            message_id=f"fake-{len(self.calls):08d}",
            cost=Decimal("0.50"),
            raw={"provider": self.provider, "ok": True},
        )

    def reset(self) -> None:
        self.calls.clear()

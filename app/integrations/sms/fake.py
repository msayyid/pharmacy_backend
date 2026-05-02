"""In-process SMS queue — logs and records messages for tests / dev.

The structured log line carries the OTP body so the curl smoke recipe in
``BUILD_PROGRESS.md`` can read the code from ``make dev`` output. Phone
numbers are masked by the structlog ``redact_pii`` processor.

Reference: BACKEND_BLUEPRINT.md §10; PRODUCT_BLUEPRINT.md §14.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.integrations.sms.base import SmsMessage

log = get_logger(__name__)


class FakeSmsQueue:
    """In-process SMS queue. Stores every enqueued message in :attr:`sent`."""

    def __init__(self) -> None:
        self.sent: list[SmsMessage] = []

    async def enqueue(self, message: SmsMessage) -> None:
        self.sent.append(message)
        # ``phone`` is masked by the redact_pii processor; ``body`` stays
        # visible so dev/test can read OTP codes.
        log.info(
            "sms_enqueued",
            purpose=message.purpose,
            phone=message.phone,
            body=message.body,
        )

    def reset(self) -> None:
        """Clear the in-memory log. Tests call this between scenarios."""
        self.sent.clear()

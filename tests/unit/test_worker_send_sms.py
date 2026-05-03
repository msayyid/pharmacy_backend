"""Unit tests — ``app.workers.sms.send_sms`` worker function.

The worker function opens its own session via ``session_scope``;
tests pre-seed an ``sms_log`` row through the test session, run the
worker, then ``session.refresh`` to see the worker's commit.
"""

from __future__ import annotations

import secrets

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.ops.models import SmsLog
from app.domain.ops.repositories import SmsLogRepository
from app.integrations.sms.factory import set_sms_client
from app.integrations.sms.fake import FakeSmsClient
from app.workers.sms import send_sms

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_sms_client():  # type: ignore[no-untyped-def]
    client = FakeSmsClient()
    set_sms_client(client)
    yield client
    set_sms_client(None)


async def test_send_sms_marks_row_sent(
    session: AsyncSession,
    fake_sms_client,  # type: ignore[no-untyped-def]
    redis_clean,  # type: ignore[no-untyped-def]
    worker_session_scope,  # type: ignore[no-untyped-def]
) -> None:
    phone = f"+99670{secrets.randbelow(10**6):07d}"
    row = await SmsLogRepository(session).create_queued(
        phone=phone, body="Hello", purpose="otp", provider="fake"
    )
    await session.commit()

    await send_sms(ctx={}, sms_log_id=row.id, phone=phone, body="Hello", purpose="otp")

    await session.refresh(row)
    assert row.status == "sent"
    assert row.provider_message_id is not None
    assert row.sent_at is not None
    assert fake_sms_client.calls == [(phone, "Hello")]


async def test_send_sms_marks_row_failed_on_provider_error(
    session: AsyncSession,
    redis_clean,  # type: ignore[no-untyped-def]
    worker_session_scope,  # type: ignore[no-untyped-def]
) -> None:
    """If the SMS client raises, the worker should mark the row failed
    + re-raise (ARQ retries per max_tries)."""

    class BoomClient:
        provider = "boom"

        async def send(self, *, phone: str, body: str):  # type: ignore[no-untyped-def]
            raise RuntimeError("nikita is down")

    set_sms_client(BoomClient())  # type: ignore[arg-type]
    try:
        phone = f"+99670{secrets.randbelow(10**6):07d}"
        row = await SmsLogRepository(session).create_queued(
            phone=phone, body="x", purpose="otp", provider="fake"
        )
        await session.commit()

        with pytest.raises(RuntimeError, match="nikita is down"):
            await send_sms(ctx={}, sms_log_id=row.id, phone=phone, body="x", purpose="otp")

        await session.refresh(row)
        assert row.status == "failed"
        assert row.error is not None
        assert "nikita is down" in row.error
    finally:
        set_sms_client(None)


async def test_send_sms_unknown_log_id_does_not_crash(
    session: AsyncSession,
    fake_sms_client,  # type: ignore[no-untyped-def]
    redis_clean,  # type: ignore[no-untyped-def]
    worker_session_scope,  # type: ignore[no-untyped-def]
) -> None:
    """sms_log_id pointing to a non-existent row should not crash; the
    SmsLogRepository.mark_sent / mark_failed methods short-circuit."""
    msg_id = await send_sms(
        ctx={},
        sms_log_id=999_999_999,
        phone="+996700000000",
        body="ghost",
        purpose="otp",
    )
    # Returns the provider's message_id even though there's no row to update.
    assert msg_id is not None
    # Sanity: SmsLog table has no row for this id.
    fresh = await session.get(SmsLog, 999_999_999)
    assert fresh is None

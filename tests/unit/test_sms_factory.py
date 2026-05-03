"""Unit tests — SMS client factory + FakeSmsClient + FakeSmsQueue.

Verifies the provider switch works, the fake records calls, and the
queue's ``sms_log`` write happens when wired up.
"""

from __future__ import annotations

import secrets

import pytest

from app.core.config import Settings
from app.integrations.sms.base import SmsMessage
from app.integrations.sms.factory import get_sms_client, set_sms_client
from app.integrations.sms.fake import FakeSmsClient, FakeSmsQueue

pytestmark = pytest.mark.unit


def _settings_with(provider: str) -> Settings:
    """Build a Settings instance with the SMS provider overridden.

    Reading from env would couple to dev secrets; we want pure unit
    tests that don't touch I/O.
    """
    return Settings(
        environment="test",
        secret_key="x" * 32,
        password_pepper="x" * 32,
        otp_pepper="x" * 32,
        mysql_dsn="mysql+asyncmy://test:test@localhost:3307/pharmacy_test",
        redis_dsn="redis://localhost:6379/15",
        sms_provider=provider,  # type: ignore[arg-type]
        sms_api_url="https://example.com/sms",  # type: ignore[arg-type]
    )


def test_factory_returns_fake_when_provider_is_fake() -> None:
    set_sms_client(None)  # clear cache
    client = get_sms_client(_settings_with("fake"))
    assert isinstance(client, FakeSmsClient)
    assert client.provider == "fake"


def test_factory_returns_nikita_scaffold_when_provider_is_nikita() -> None:
    from app.integrations.sms.nikita import NikitaSmsClient

    set_sms_client(None)
    client = get_sms_client(_settings_with("nikita"))
    assert isinstance(client, NikitaSmsClient)
    assert client.provider == "nikita"


async def test_fake_client_send_records_call() -> None:
    client = FakeSmsClient()
    result = await client.send(phone="+996700123456", body="Test")
    assert result.message_id is not None
    assert client.calls == [("+996700123456", "Test")]


async def test_fake_client_reset_clears_calls() -> None:
    client = FakeSmsClient()
    await client.send(phone="+996700123456", body="A")
    await client.send(phone="+996700123456", body="B")
    assert len(client.calls) == 2
    client.reset()
    assert client.calls == []


async def test_nikita_send_raises_not_implemented() -> None:
    """Real Nikita adapter is scaffold-only; ``send`` must refuse."""
    from app.integrations.sms.nikita import NikitaSmsClient

    s = _settings_with("nikita")
    client = NikitaSmsClient(s)
    try:
        with pytest.raises(NotImplementedError, match="OPEN_QUESTIONS Q13"):
            await client.send(phone="+996700123456", body="Test")
    finally:
        await client.aclose()


async def test_fake_queue_records_in_memory() -> None:
    """Queue with no session_factory just records to ``sent``."""
    queue = FakeSmsQueue()
    msg = SmsMessage(phone="+996700123456", body="Hello", purpose="otp")
    await queue.enqueue(msg)
    assert queue.sent == [msg]


async def test_fake_queue_with_session_writes_sms_log_row(session, redis_clean) -> None:  # type: ignore[no-untyped-def]
    """Queue with a session_factory writes a sms_log row per enqueue."""
    from sqlalchemy import func, select

    from app.core.db import SessionLocal
    from app.domain.ops.models import SmsLog

    async def _factory():
        async with SessionLocal() as s:
            yield s

    queue = FakeSmsQueue(session_factory=_factory)
    msg = SmsMessage(
        phone=f"+99670{secrets.randbelow(10**6):07d}",
        body="Test SMS log write",
        purpose="order_confirmed",
    )
    await queue.enqueue(msg)

    # Read back via the test-session.
    rows = (
        (
            await session.execute(
                select(SmsLog).where(SmsLog.phone == msg.phone).order_by(SmsLog.id.desc()).limit(1)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].body == msg.body
    assert rows[0].purpose == msg.purpose
    assert rows[0].status == "queued"
    assert rows[0].provider == "fake"

    # Cleanup so the next test starts clean.
    await session.execute(SmsLog.__table__.delete().where(SmsLog.phone == msg.phone))
    await session.commit()
    _ = func  # keep import used

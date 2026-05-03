"""Unit tests — payment client factory + FakePaymentClient + scaffold guard."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import Settings
from app.integrations.payments.base import InvalidSignatureError
from app.integrations.payments.factory import (
    get_payment_client,
    set_payment_client,
)
from app.integrations.payments.fake import FakePaymentClient

pytestmark = pytest.mark.unit


def _settings_with(provider: str) -> Settings:
    return Settings(
        environment="test",
        secret_key="x" * 32,
        password_pepper="x" * 32,
        otp_pepper="x" * 32,
        mysql_dsn="mysql+asyncmy://test:test@localhost:3307/pharmacy_test",
        redis_dsn="redis://localhost:6379/15",
        payment_provider=provider,  # type: ignore[arg-type]
        payment_api_url="https://example.com/pay",  # type: ignore[arg-type]
        payment_merchant_id="merchant-1",
        payment_secret="secret-x" * 4,  # type: ignore[arg-type]
    )


def test_factory_returns_fake_when_provider_is_fake() -> None:
    set_payment_client(None)
    client = get_payment_client(_settings_with("fake"))
    assert isinstance(client, FakePaymentClient)
    assert client.provider == "fake"


def test_factory_returns_freedom_pay_scaffold_when_provider_is_freedom_pay() -> None:
    from app.integrations.payments.freedom_pay import FreedomPayClient

    set_payment_client(None)
    client = get_payment_client(_settings_with("freedom_pay"))
    assert isinstance(client, FreedomPayClient)
    assert client.provider == "freedom_pay"


async def test_fake_create_intent_returns_redirect_and_records() -> None:
    client = FakePaymentClient()
    result = await client.create_intent(
        order_id="abcdef0123456789",
        order_number="PH-2026-000001",
        amount=Decimal("250"),
        currency="KGS",
        recipient_phone="+996700123456",
        return_url="https://example.com/return",
    )
    assert result.redirect_url.startswith("https://payments.fake/pay/")
    assert result.provider_transaction_id.startswith("fake-txn-")
    assert len(client.intents) == 1
    assert client.intents[0]["order_number"] == "PH-2026-000001"


async def test_fake_refund_returns_id_and_records() -> None:
    client = FakePaymentClient()
    result = await client.refund(
        provider_transaction_id="fake-txn-123",
        amount=Decimal("100"),
        reason="customer_request",
    )
    assert result.refund_id.startswith("fake-refund-")
    assert client.refunds[0]["amount"] == "100"


async def test_fake_verify_webhook_rejects_bad_signature() -> None:
    client = FakePaymentClient(signing_token="abc")
    body = b'{"event_id":"e1"}'
    with pytest.raises(InvalidSignatureError):
        await client.verify_webhook(body=body, signature="wrong")


async def test_fake_verify_webhook_accepts_correct_signature() -> None:
    import orjson

    client = FakePaymentClient(signing_token="abc")
    payload = client.make_event_payload(
        provider_transaction_id="fake-txn-abc",
        amount=Decimal("100"),
        event_type="charge_succeeded",
    )
    body = orjson.dumps(payload)
    sig = client.sign(body)
    event = await client.verify_webhook(body=body, signature=sig)
    assert event.provider_transaction_id == "fake-txn-abc"
    assert event.event_type == "charge_succeeded"
    assert event.amount == Decimal("100")
    assert event.is_refund is False


async def test_freedom_pay_scaffold_methods_raise_not_implemented() -> None:
    from app.integrations.payments.freedom_pay import FreedomPayClient

    client = FreedomPayClient(_settings_with("freedom_pay"))
    try:
        with pytest.raises(NotImplementedError, match="OPEN_QUESTIONS Q14"):
            await client.create_intent(
                order_id="oid",
                order_number="PH-2026-000001",
                amount=Decimal("100"),
                currency="KGS",
                recipient_phone="+996700111222",
                return_url="https://example.com/r",
            )
        with pytest.raises(NotImplementedError, match="OPEN_QUESTIONS Q14"):
            await client.refund(
                provider_transaction_id="x",
                amount=Decimal("10"),
                reason=None,
            )
        with pytest.raises(NotImplementedError, match="OPEN_QUESTIONS Q14"):
            await client.verify_webhook(body=b"{}", signature="x")
    finally:
        await client.aclose()

"""Integration — Freedom Pay webhook receiver.

* Invalid signature → 400 ``invalid_signature``.
* Charge-succeeded → ``Payment.status='paid'``, ``Order.payment_status='paid'``.
* Refund-succeeded → ``Payment.status='paid'`` on the refund row,
  ``Order.payment_status='refunded'``.
* Idempotent replay → second call with same ``event_id`` is a
  no-op (returns ``"duplicate"``).
"""

from __future__ import annotations

import secrets
from decimal import Decimal

import orjson
import pytest
from httpx import AsyncClient

from app.core.types import uuid7
from app.domain.orders.models import (
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.integrations.payments.factory import set_payment_client
from app.integrations.payments.fake import FakePaymentClient
from tests.factories.inventory import seed_branch

pytestmark = pytest.mark.integration


WEBHOOK_PATH = "/api/webhooks/payments/freedom-pay"


@pytest.fixture
def fake_payment_client():  # type: ignore[no-untyped-def]
    """Inject a FakePaymentClient with a known signing token."""
    client = FakePaymentClient(signing_token="test-token-xyz")
    set_payment_client(client)
    yield client
    set_payment_client(None)


async def _seed_order_with_payment(
    session,  # type: ignore[no-untyped-def]
    *,
    branch_id: int,
    is_refund: bool = False,
) -> tuple[Order, Payment]:
    """Insert one Order + one Payment row in pending state."""
    order = Order(
        id=uuid7(),
        order_number=f"PH-WH-{secrets.token_hex(6).upper()}",
        user_id=None,
        branch_id=branch_id,
        status=OrderStatus.PENDING.value,
        payment_status=PaymentStatus.PENDING.value,
        payment_method=PaymentMethod.CARD_ONLINE.value,
        delivery_method="pickup",
        recipient_name="Test",
        recipient_phone="+996700000000",
        subtotal=Decimal("250"),
        delivery_fee=Decimal("0"),
        discount_amount=Decimal("0"),
        total=Decimal("250"),
        currency="KGS",
    )
    session.add(order)
    await session.flush()

    txn = f"fake-txn-{secrets.token_hex(6)}"
    payment = Payment(
        id=uuid7(),
        order_id=order.id,
        provider="fake",
        provider_transaction_id=txn,
        amount=Decimal("250"),
        currency="KGS",
        status=PaymentStatus.PENDING.value,
        is_refund=is_refund,
    )
    session.add(payment)
    await session.commit()
    return order, payment


async def test_invalid_signature_rejected(
    client: AsyncClient,
    fake_payment_client,  # type: ignore[no-untyped-def]
) -> None:
    body = orjson.dumps({"event_id": "x", "event_type": "charge_succeeded"})
    r = await client.post(
        WEBHOOK_PATH,
        content=body,
        headers={"X-Signature": "wrong-sig", "Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_signature"


async def test_charge_succeeded_flips_payment_and_order(
    client: AsyncClient,
    session,  # type: ignore[no-untyped-def]
    fake_payment_client,  # type: ignore[no-untyped-def]
    redis_clean,  # type: ignore[no-untyped-def]
) -> None:
    branch = await seed_branch(session, code=f"WH-{secrets.token_hex(3)}")
    await session.commit()
    order, payment = await _seed_order_with_payment(session, branch_id=branch.id)

    payload = fake_payment_client.make_event_payload(
        provider_transaction_id=payment.provider_transaction_id,
        amount=Decimal("250"),
        event_type="charge_succeeded",
    )
    body = orjson.dumps(payload)
    sig = fake_payment_client.sign(body)

    r = await client.post(
        WEBHOOK_PATH,
        content=body,
        headers={"X-Signature": sig, "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied"

    # Re-load fresh — the identity-map cache from the seed would
    # otherwise return stale objects with their pre-webhook state.
    await session.refresh(payment)
    await session.refresh(order)
    fresh_payment, fresh_order = payment, order
    assert fresh_payment.status == PaymentStatus.PAID.value
    assert fresh_payment.paid_at is not None
    assert fresh_order.payment_status == PaymentStatus.PAID.value


async def test_refund_succeeded_flips_payment_and_order(
    client: AsyncClient,
    session,  # type: ignore[no-untyped-def]
    fake_payment_client,  # type: ignore[no-untyped-def]
    redis_clean,  # type: ignore[no-untyped-def]
) -> None:
    branch = await seed_branch(session, code=f"WH-{secrets.token_hex(3)}")
    await session.commit()
    order, refund = await _seed_order_with_payment(session, branch_id=branch.id, is_refund=True)
    # Order must already be 'paid' before a refund event makes sense.
    order.payment_status = PaymentStatus.PAID.value
    await session.commit()

    payload = fake_payment_client.make_event_payload(
        provider_transaction_id=refund.provider_transaction_id,
        amount=Decimal("250"),  # full refund
        event_type="refund_succeeded",
    )
    body = orjson.dumps(payload)
    r = await client.post(
        WEBHOOK_PATH,
        content=body,
        headers={"X-Signature": fake_payment_client.sign(body)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied"

    await session.refresh(refund)
    await session.refresh(order)
    assert refund.status == PaymentStatus.PAID.value
    assert order.payment_status == PaymentStatus.REFUNDED.value


async def test_idempotent_replay_returns_duplicate(
    client: AsyncClient,
    session,  # type: ignore[no-untyped-def]
    fake_payment_client,  # type: ignore[no-untyped-def]
    redis_clean,  # type: ignore[no-untyped-def]
) -> None:
    branch = await seed_branch(session, code=f"WH-{secrets.token_hex(3)}")
    await session.commit()
    _, payment = await _seed_order_with_payment(session, branch_id=branch.id)

    event_id = f"evt-{secrets.token_hex(8)}"
    payload = fake_payment_client.make_event_payload(
        provider_transaction_id=payment.provider_transaction_id,
        amount=Decimal("250"),
        event_type="charge_succeeded",
        event_id=event_id,
    )
    body = orjson.dumps(payload)
    sig = fake_payment_client.sign(body)

    r1 = await client.post(WEBHOOK_PATH, content=body, headers={"X-Signature": sig})
    assert r1.status_code == 200
    assert r1.json()["status"] == "applied"

    r2 = await client.post(WEBHOOK_PATH, content=body, headers={"X-Signature": sig})
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"


async def test_no_match_for_unknown_transaction_id(
    client: AsyncClient,
    fake_payment_client,  # type: ignore[no-untyped-def]
    redis_clean,  # type: ignore[no-untyped-def]
) -> None:
    payload = fake_payment_client.make_event_payload(
        provider_transaction_id="fake-txn-NONEXISTENT",
        amount=Decimal("100"),
        event_type="charge_succeeded",
    )
    body = orjson.dumps(payload)
    r = await client.post(
        WEBHOOK_PATH,
        content=body,
        headers={"X-Signature": fake_payment_client.sign(body)},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "no_match"

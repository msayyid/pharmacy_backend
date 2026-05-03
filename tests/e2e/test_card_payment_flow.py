"""E2E — card-payment flow.

Walks the customer journey for a card_online order:

1. Guest cart → add item → OTP login → place card order.
   Place response carries a ``payment_redirect_url`` (the gateway's
   hosted checkout). A pending ``Payment`` row is persisted with the
   gateway's ``provider_transaction_id``.
2. Simulate the gateway calling our webhook
   (``POST /api/webhooks/payments/freedom-pay``) with a signed
   ``charge_succeeded`` event for that transaction id.
3. Order's ``payment_status`` flips to ``paid``; the Payment row's
   ``status`` flips to ``paid`` with ``paid_at`` set.

Uses :class:`FakePaymentClient` injected via the factory cache so the
real adapter's NotImplementedError stub stays out of the path.
"""

from __future__ import annotations

import secrets
from datetime import date, timedelta
from decimal import Decimal

import orjson
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.types import uuid7
from app.domain.catalog.models import (
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
)
from app.domain.inventory.models import Branch, BranchProduct, InventoryBatch
from app.domain.orders.models import Order, Payment, PaymentStatus
from app.integrations.payments.factory import set_payment_client
from app.integrations.payments.fake import FakePaymentClient

pytestmark = pytest.mark.e2e


WEBHOOK_PATH = "/api/webhooks/payments/freedom-pay"


@pytest.fixture
def fake_payment_client():  # type: ignore[no-untyped-def]
    client = FakePaymentClient(signing_token="e2e-token-9k")
    set_payment_client(client)
    yield client
    set_payment_client(None)


async def _seed_card_store() -> dict:
    """Commit a (branch, product, batch) so the storefront flow works."""
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    out: dict = {}
    try:
        async with factory() as s:
            existing = (await s.execute(select(Branch).where(Branch.id == 1))).scalar_one_or_none()
            if existing is None:
                branch = Branch(
                    code=f"CDP-{secrets.token_hex(4).upper()}",
                    name="Card Pay",
                    address="мкр Асанбай 12",
                    is_active=True,
                )
                s.add(branch)
                await s.flush()
                branch_id = branch.id
            else:
                branch_id = existing.id
            out["branch_id"] = branch_id

            cat = Category(
                slug=f"cdp-{secrets.token_hex(4)}",
                is_active=True,
                sort_order=0,
            )
            cat.translations.append(CategoryTranslation(language_code="ru", name="Карта"))
            s.add(cat)
            await s.flush()

            product = Product(
                id=uuid7(),
                sku=f"CDP-{secrets.token_hex(4).upper()}",
                slug=f"cdp-{secrets.token_hex(4)}",
                category_id=cat.id,
                form="tablet",
                is_active=True,
                is_featured=False,
                requires_prescription=False,
                requires_cold_chain=False,
            )
            product.translations.append(
                ProductTranslation(language_code="ru", name="Карта-продукт"),
            )
            s.add(product)
            await s.flush()
            out["product_id"] = str(product.id)

            s.add(
                BranchProduct(
                    branch_id=branch_id,
                    product_id=product.id,
                    price=Decimal("250"),
                    currency="KGS",
                    is_available=True,
                    total_quantity=20,
                    reserved_quantity=0,
                    low_stock_threshold=5,
                ),
            )
            s.add(
                InventoryBatch(
                    branch_id=branch_id,
                    product_id=product.id,
                    batch_number=f"CDP-LOT-{secrets.token_hex(3)}",
                    expiry_date=date.today() + timedelta(days=365),
                    quantity_received=20,
                    quantity_remaining=20,
                    quantity_reserved=0,
                    cost_price=Decimal("125"),
                    currency="KGS",
                ),
            )
            await s.commit()
        return out
    finally:
        await engine.dispose()


async def _otp_login(client: AsyncClient, phone: str) -> str:
    from tests.e2e.conftest import (
        extract_otp_from_messages,
        install_fresh_sms_queue,
    )

    sms_queue = install_fresh_sms_queue()
    r = await client.post("/api/v1/auth/otp/request", json={"phone": phone})
    assert r.status_code == 202, r.text
    code = extract_otp_from_messages(sms_queue.sent)
    assert code is not None
    r2 = await client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": code})
    assert r2.status_code == 200, r2.text
    return r2.json()["access_token"]


async def test_card_payment_place_then_webhook_marks_paid(
    client: AsyncClient,
    fake_payment_client,  # type: ignore[no-untyped-def]
    redis_clean: None,
) -> None:
    seed = await _seed_card_store()
    phone = f"+99670{secrets.randbelow(10**6):07d}"
    access = await _otp_login(client, phone)

    # Add to cart.
    r_add = await client.post(
        "/api/v1/cart/items",
        json={"product_id": seed["product_id"], "quantity": 1},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert r_add.status_code == 201, r_add.text

    # Place card order.
    r_place = await client.post(
        "/api/v1/checkout/place",
        json={
            "delivery_method": "pickup",
            "payment_method": "card_online",
            "recipient_name": "Тест",
            "recipient_phone": phone,
        },
        headers={
            "Authorization": f"Bearer {access}",
            "Idempotency-Key": f"e2e-{secrets.token_hex(8)}",
        },
    )
    assert r_place.status_code == 201, r_place.text
    body = r_place.json()
    assert body["payment_status"] == "pending"
    assert body["payment_redirect_url"].startswith("https://payments.fake/pay/")
    assert len(fake_payment_client.intents) == 1
    txn = fake_payment_client.intents[0]["txn"]

    # Simulate the gateway webhook.
    payload = fake_payment_client.make_event_payload(
        provider_transaction_id=txn,
        amount=Decimal(body["total"]),
        event_type="charge_succeeded",
    )
    raw_body = orjson.dumps(payload)
    r_hook = await client.post(
        WEBHOOK_PATH,
        content=raw_body,
        headers={
            "X-Signature": fake_payment_client.sign(raw_body),
            "Content-Type": "application/json",
        },
    )
    assert r_hook.status_code == 200, r_hook.text
    assert r_hook.json()["status"] == "applied"

    # Verify in DB: order paid + Payment row paid.
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            order = (
                await s.execute(select(Order).where(Order.order_number == body["order_number"]))
            ).scalar_one()
            assert order.payment_status == PaymentStatus.PAID.value
            payment = (
                await s.execute(
                    select(Payment).where(
                        Payment.order_id == order.id,
                        Payment.is_refund == False,  # noqa: E712
                    )
                )
            ).scalar_one()
            assert payment.status == PaymentStatus.PAID.value
            assert payment.provider_transaction_id == txn
            assert payment.paid_at is not None
    finally:
        await engine.dispose()

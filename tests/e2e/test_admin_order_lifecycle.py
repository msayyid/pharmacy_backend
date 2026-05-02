"""E2E — admin order lifecycle over HTTP.

Customer places an order; admin (super_admin) walks it through:
confirm → start-preparing → mark-ready → mark-delivered.

Then verifies RBAC: pharmacist cannot refund, content_editor cannot
view orders.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
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
from app.domain.catalog.repositories import ProductRepository
from app.domain.identity.models import User
from app.domain.identity.repositories import UserAddressRepository
from app.domain.inventory.models import Branch, BranchProduct, InventoryBatch
from app.domain.inventory.repositories import (
    BranchProductRepository,
    BranchRepository,
    InventoryBatchRepository,
    StockMovementRepository,
    SupplierRepository,
)
from app.domain.inventory.services import InventoryService
from app.domain.ops.repositories import AdminAuditLogRepository
from app.domain.ops.services import AdminAuditLogService
from app.domain.orders.cart_service import CartService
from app.domain.orders.checkout_service import CheckoutService
from app.domain.orders.repositories import (
    CartRepository,
    OrderRepository,
    OrderSequenceRepository,
    OrderStatusHistoryRepository,
)
from app.domain.orders.schemas import PlaceOrderRequest
from tests.e2e.conftest import seed_admin_committed

pytestmark = pytest.mark.e2e


async def _seed_branch_and_product() -> dict:
    """Commit a branch+product so admin endpoints have something to act on."""
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    out: dict = {}
    try:
        async with factory() as s:
            branch = Branch(
                code=f"AOL-{secrets.token_hex(4).upper()}",
                name="Admin Lifecycle",
                address="мкр Асанбай 12",
                is_active=True,
            )
            s.add(branch)
            await s.flush()
            out["branch_id"] = branch.id

            cat = Category(
                slug=f"aol-{secrets.token_hex(4)}",
                is_active=True,
                sort_order=0,
            )
            cat.translations.append(CategoryTranslation(language_code="ru", name="Тест"))
            s.add(cat)
            await s.flush()

            product = Product(
                id=uuid7(),
                sku=f"AOL-{secrets.token_hex(4)}",
                slug=f"aol-{secrets.token_hex(4)}",
                category_id=cat.id,
                form="tablet",
                is_active=True,
                is_featured=False,
                requires_prescription=False,
                requires_cold_chain=False,
            )
            product.translations.append(ProductTranslation(language_code="ru", name="Тест-продукт"))
            s.add(product)
            await s.flush()
            out["product_id"] = product.id

            bp = BranchProduct(
                branch_id=branch.id,
                product_id=product.id,
                price=Decimal("100"),
                currency="KGS",
                is_available=True,
                total_quantity=20,
                reserved_quantity=0,
                low_stock_threshold=5,
            )
            s.add(bp)
            s.add(
                InventoryBatch(
                    branch_id=branch.id,
                    product_id=product.id,
                    batch_number=f"AOL-LOT-{secrets.token_hex(3)}",
                    expiry_date=date.today() + timedelta(days=365),
                    quantity_received=20,
                    quantity_remaining=20,
                    quantity_reserved=0,
                    cost_price=Decimal("50"),
                    currency="KGS",
                )
            )
            # Create a real order via the place-order flow so it has
            # OrderItems + reserved stock_movements (needed for the
            # convert_reservation_to_sold path).
            user = User(
                id=uuid7(),
                phone=f"+99670{secrets.randbelow(10**6):07d}",
                preferred_language="ru",
                is_phone_verified=True,
                is_active=True,
            )
            s.add(user)
            await s.flush()

            cart_svc = CartService(
                carts=CartRepository(s),
                products=ProductRepository(s),
                branch_products=BranchProductRepository(s),
            )
            inv_svc = InventoryService(
                session=s,
                branches=BranchRepository(s),
                suppliers=SupplierRepository(s),
                branch_products=BranchProductRepository(s),
                batches=InventoryBatchRepository(s),
                movements=StockMovementRepository(s),
                audit=AdminAuditLogService(AdminAuditLogRepository(s)),
            )
            checkout = CheckoutService(
                carts=CartRepository(s),
                orders=OrderRepository(s),
                order_history=OrderStatusHistoryRepository(s),
                order_sequence=OrderSequenceRepository(s),
                products=ProductRepository(s),
                branch_products=BranchProductRepository(s),
                batches=InventoryBatchRepository(s),
                addresses=UserAddressRepository(s),
                inventory=inv_svc,
            )
            cart = await cart_svc.get_or_create(branch_id=branch.id, user=user, session_id=None)
            await cart_svc.add_item(cart=cart, product_id=product.id, quantity=2)
            full = await cart_svc.get_with_items(cart.id)
            assert full is not None
            response = await checkout.place_order(
                cart=full,
                user=user,
                payload=PlaceOrderRequest(
                    delivery_method="pickup",
                    payment_method="cash_on_delivery",
                    recipient_name="Test",
                    recipient_phone="+996700000000",
                ),
                idempotency_key=f"e2e-{secrets.token_hex(6)}",
                body_digest=f"d-{secrets.token_hex(6)}",
            )
            out["order_id"] = str(response.order_id)
            await s.commit()
        return out
    finally:
        await engine.dispose()


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@pharmacy.kg"


async def _login_admin(
    client: AsyncClient, *, role: str, branch_id: int | None = None
) -> dict[str, str]:
    email = _email(role)
    await seed_admin_committed(email=email, password="ok", role=role, branch_id=branch_id)
    r = await client.post(
        "/api/admin/v1/auth/login",
        json={"email": email, "password": "ok"},
    )
    assert r.status_code == 200, r.text
    return {"admin_session": r.cookies["admin_session"]}


# ─── Lifecycle walk ──────────────────────────────────────────────────────────


async def test_super_admin_walks_order_to_delivered(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_branch_and_product()
    cookies = await _login_admin(client, role="super_admin")

    r = await client.post(f"/api/admin/v1/orders/{seed['order_id']}/confirm", cookies=cookies)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "confirmed"

    r2 = await client.post(
        f"/api/admin/v1/orders/{seed['order_id']}/start-preparing",
        cookies=cookies,
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "preparing"

    r3 = await client.post(
        f"/api/admin/v1/orders/{seed['order_id']}/mark-ready",
        cookies=cookies,
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "ready_for_pickup"

    r4 = await client.post(
        f"/api/admin/v1/orders/{seed['order_id']}/mark-delivered",
        cookies=cookies,
    )
    assert r4.status_code == 200
    assert r4.json()["status"] == "delivered"


async def test_admin_cancels_pending_order(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_branch_and_product()
    cookies = await _login_admin(client, role="super_admin")

    r = await client.post(
        f"/api/admin/v1/orders/{seed['order_id']}/cancel",
        json={"reason": "customer_changed_mind"},
        cookies=cookies,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    assert r.json()["cancel_reason"] == "customer_changed_mind"


async def test_admin_list_orders_filters(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_branch_and_product()
    cookies = await _login_admin(client, role="super_admin")
    r = await client.get(
        f"/api/admin/v1/orders?branch_id={seed['branch_id']}",
        cookies=cookies,
    )
    assert r.status_code == 200
    body = r.json()
    assert any(o["id"] == seed["order_id"] for o in body["items"])


# ─── RBAC ────────────────────────────────────────────────────────────────────


async def test_content_editor_cannot_view_orders(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_branch_and_product()
    cookies = await _login_admin(client, role="content_editor", branch_id=seed["branch_id"])
    r = await client.get("/api/admin/v1/orders", cookies=cookies)
    assert r.status_code == 403


async def test_pharmacist_cannot_refund(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_branch_and_product()
    cookies = await _login_admin(client, role="pharmacist", branch_id=seed["branch_id"])
    r = await client.post(
        f"/api/admin/v1/orders/{seed['order_id']}/refund",
        json={"amount": "10.00", "reason": "test"},
        headers={"Idempotency-Key": secrets.token_hex(8)},
        cookies=cookies,
    )
    assert r.status_code == 403

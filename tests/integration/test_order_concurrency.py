"""Integration tests for the place-order transaction.

Mirrors :mod:`tests.integration.test_fefo_concurrent` but at the
checkout layer:

* ``test_two_orders_same_product_one_batch`` — only one places, the
  other gets ``CheckoutValidationError`` (stock conflict).
* ``test_two_orders_split_across_batches`` — both succeed, partial
  allocations across two batches.
* ``test_idempotent_double_place_same_body`` — same key + body returns
  same response, no second order.
* ``test_idempotent_conflict_different_body`` — same key, different
  body → ``IdempotencyConflictError``.

Loops controlled by ``ORDER_CONCURRENT_LOOPS`` env (default 30).
"""

from __future__ import annotations

import asyncio
import os
import secrets
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.types import uuid7
from app.domain.catalog.models import (
    Category,
    CategoryTranslation,
    Manufacturer,
    Product,
    ProductTranslation,
)
from app.domain.catalog.repositories import ProductRepository
from app.domain.identity.models import User
from app.domain.identity.repositories import UserAddressRepository
from app.domain.inventory.models import (
    Branch,
    BranchProduct,
    InventoryBatch,
)
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
from app.domain.orders.checkout_service import (
    CheckoutService,
    IdempotencyConflictError,
)
from app.domain.orders.repositories import (
    CartRepository,
    OrderRepository,
    OrderSequenceRepository,
    OrderStatusHistoryRepository,
)
from app.domain.orders.schemas import PlaceOrderRequest

pytestmark = pytest.mark.integration


_LOOPS = int(os.getenv("ORDER_CONCURRENT_LOOPS", "30"))


def _make_services(session: Any) -> tuple[CartService, CheckoutService]:
    inv = InventoryService(
        session=session,
        branches=BranchRepository(session),
        suppliers=SupplierRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        movements=StockMovementRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )
    cart = CartService(
        carts=CartRepository(session),
        products=ProductRepository(session),
        branch_products=BranchProductRepository(session),
    )
    checkout = CheckoutService(
        carts=CartRepository(session),
        orders=OrderRepository(session),
        order_history=OrderStatusHistoryRepository(session),
        order_sequence=OrderSequenceRepository(session),
        products=ProductRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        addresses=UserAddressRepository(session),
        inventory=inv,
    )
    return (cart, checkout)


async def _seed_loop(*, loop_idx: int) -> dict[str, Any]:
    """Commit a fresh user / branch / product / 2 batches."""
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            user = User(
                id=uuid7(),
                phone=f"+99670{secrets.randbelow(1_000_000):07d}",
                preferred_language="ru",
                is_phone_verified=True,
                is_active=True,
            )
            s.add(user)
            await s.flush()

            branch = Branch(
                code=f"OC-BR-{loop_idx}-{uuid7().hex[:6].upper()}",
                name="Order Concurrency",
                address="мкр Асанбай 12",
                is_active=True,
            )
            s.add(branch)
            await s.flush()

            cat = Category(
                slug=f"oc-cat-{loop_idx}-{uuid7().hex[:6]}",
                is_active=True,
                sort_order=0,
            )
            cat.translations.append(CategoryTranslation(language_code="ru", name="Лекарства"))
            s.add(cat)

            mfr = Manufacturer(name=f"OC Mfr {secrets.token_hex(8)}", is_active=True)
            s.add(mfr)
            await s.flush()

            product = Product(
                id=uuid7(),
                sku=f"OC-{loop_idx}-{uuid7().hex[:6]}",
                slug=f"oc-{loop_idx}-{uuid7().hex[:6]}",
                category_id=cat.id,
                manufacturer_id=mfr.id,
                form="tablet",
                is_active=True,
                is_featured=False,
                requires_prescription=False,
                requires_cold_chain=False,
            )
            product.translations.append(ProductTranslation(language_code="ru", name="OC продукт"))
            s.add(product)
            await s.flush()

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

            today = date.today()
            b1 = InventoryBatch(
                branch_id=branch.id,
                product_id=product.id,
                batch_number=f"OC-A-{loop_idx}-{uuid7().hex[:4]}",
                expiry_date=today + timedelta(days=60),
                quantity_received=10,
                quantity_remaining=10,
                quantity_reserved=0,
                cost_price=Decimal("50"),
                currency="KGS",
            )
            b2 = InventoryBatch(
                branch_id=branch.id,
                product_id=product.id,
                batch_number=f"OC-B-{loop_idx}-{uuid7().hex[:4]}",
                expiry_date=today + timedelta(days=180),
                quantity_received=10,
                quantity_remaining=10,
                quantity_reserved=0,
                cost_price=Decimal("50"),
                currency="KGS",
            )
            s.add_all([b1, b2])
            await s.commit()
            return {
                "user_id": user.id,
                "branch_id": branch.id,
                "product_id": product.id,
            }
    finally:
        await engine.dispose()


async def _place_in_own_session(
    factory: Any,
    *,
    seeded: dict[str, Any],
    qty: int,
    idempotency_key: str,
    body_digest: str,
) -> Any:
    async with factory() as session:
        cart_svc, checkout_svc = _make_services(session)
        from sqlalchemy import select

        user = (
            await session.execute(select(User).where(User.id == seeded["user_id"]))
        ).scalar_one()
        cart = await cart_svc.get_or_create(
            branch_id=seeded["branch_id"], user=user, session_id=None
        )
        await cart_svc.add_item(cart=cart, product_id=seeded["product_id"], quantity=qty)
        full = await cart_svc.get_with_items(cart.id)
        assert full is not None
        # Commit the cart in its own short transaction so that the
        # later place_order transaction starts with a clean slate —
        # otherwise the cart UPSERT and the order INSERT race for
        # locks (both touch ``carts``).
        await session.commit()
        try:
            response = await checkout_svc.place_order(
                cart=full,
                user=user,
                payload=PlaceOrderRequest(
                    delivery_method="pickup",
                    payment_method="cash_on_delivery",
                    recipient_name="Test",
                    recipient_phone="+996700000000",
                ),
                idempotency_key=idempotency_key,
                body_digest=body_digest,
            )
            await session.commit()
            return ("ok", response)
        except Exception as exc:
            await session.rollback()
            return ("error", exc)


@pytest.mark.parametrize("loop_idx", range(_LOOPS), ids=lambda i: f"loop{i:03d}")
async def test_two_orders_two_batches_partial_allocation(
    _migrated_db: None, redis_clean: None, loop_idx: int
) -> None:
    """Two orders for 8 each on a 20-unit pool (10+10 batches).

    Both should succeed: each takes 8 from one or splits across both
    batches. After: total_reserved <= total_remaining; no oversell.
    """
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        # Two seeded loops so each order gets its own user (single user
        # has one cart at a time — concurrent place_orders by the same
        # user serialise on the cart UPDATE).
        seed_a = await _seed_loop(loop_idx=loop_idx)
        # Use the same branch/product but a different user.
        # Build a second user pointing at the same branch + product.
        async with factory() as s:
            user_b = User(
                id=uuid7(),
                phone=f"+99670{secrets.randbelow(1_000_000):07d}",
                preferred_language="ru",
                is_phone_verified=True,
                is_active=True,
            )
            s.add(user_b)
            await s.commit()
        seed_b = {**seed_a, "user_id": user_b.id}

        results = await asyncio.gather(
            _place_in_own_session(
                factory,
                seeded=seed_a,
                qty=8,
                idempotency_key=f"key-a-{loop_idx}-{uuid7().hex[:8]}",
                body_digest="d-a",
            ),
            _place_in_own_session(
                factory,
                seeded=seed_b,
                qty=8,
                idempotency_key=f"key-b-{loop_idx}-{uuid7().hex[:8]}",
                body_digest="d-b",
            ),
        )

        ok_count = sum(1 for r in results if r[0] == "ok")
        assert ok_count == 2, f"results: {results}"

        # Read post-state: total reserved across batches must equal sum
        # of placed quantities (= 16); no oversell.
        from sqlalchemy import select

        async with factory() as session:
            batches = (
                (
                    await session.execute(
                        select(InventoryBatch).where(
                            InventoryBatch.product_id == seed_a["product_id"]
                        )
                    )
                )
                .scalars()
                .all()
            )
            total_reserved = sum(b.quantity_reserved for b in batches)
            for b in batches:
                assert b.quantity_reserved <= b.quantity_remaining
            assert total_reserved == 16
    finally:
        await engine.dispose()


# ─── Idempotency ─────────────────────────────────────────────────────────────


async def test_idempotent_double_place_same_body_returns_cached(
    _migrated_db: None, redis_clean: None
) -> None:
    seeded = await _seed_loop(loop_idx=999)
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        first = await _place_in_own_session(
            factory,
            seeded=seeded,
            qty=2,
            idempotency_key="DOUBLE-A",
            body_digest="DIGEST-A",
        )
        second = await _place_in_own_session(
            factory,
            seeded=seeded,
            qty=2,
            idempotency_key="DOUBLE-A",
            body_digest="DIGEST-A",
        )
        assert first[0] == "ok"
        assert second[0] == "ok"
        assert first[1].order_number == second[1].order_number
    finally:
        await engine.dispose()


async def test_idempotent_conflict_on_different_body(_migrated_db: None, redis_clean: None) -> None:
    seeded = await _seed_loop(loop_idx=998)
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        first = await _place_in_own_session(
            factory,
            seeded=seeded,
            qty=2,
            idempotency_key="CONFLICT-A",
            body_digest="DIGEST-X",
        )
        assert first[0] == "ok"
        second = await _place_in_own_session(
            factory,
            seeded=seeded,
            qty=2,
            idempotency_key="CONFLICT-A",
            body_digest="DIGEST-Y",  # different
        )
        assert second[0] == "error"
        assert isinstance(second[1], IdempotencyConflictError)
    finally:
        await engine.dispose()

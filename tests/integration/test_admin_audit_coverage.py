"""Audit-log coverage check.

Every Phase 5 / 6 / 9 admin write must produce one ``admin_audit_log``
row. This test invokes a representative mutation per service and
asserts the log row count grows by exactly 1.
"""

from __future__ import annotations

import secrets
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.catalog.repositories import (
    ActiveIngredientRepository,
    CategoryRepository,
    ManufacturerRepository,
    SymptomRepository,
)
from app.domain.catalog.schemas import (
    CategoryCreate,
    CategoryTranslationIn,
    ManufacturerCreate,
)
from app.domain.catalog.services import CatalogAdminService
from app.domain.identity.models import AdminUser
from app.domain.inventory.repositories import (
    BranchProductRepository,
    BranchRepository,
    InventoryBatchRepository,
    StockMovementRepository,
    SupplierRepository,
)
from app.domain.inventory.schemas import (
    BatchAdjustRequest,
    BatchReceiveRequest,
)
from app.domain.inventory.services import InventoryService
from app.domain.ops.models import AdminAuditLog
from app.domain.ops.repositories import AdminAuditLogRepository
from app.domain.ops.services import AdminAuditLogService
from app.domain.orders.lifecycle import OrderLifecycleService
from app.domain.orders.repositories import (
    OrderRepository,
    OrderStatusHistoryRepository,
)
from tests.factories.catalog import seed_category, seed_product
from tests.factories.inventory import (
    seed_branch,
    seed_branch_product,
    seed_inventory_batch,
)
from tests.factories.orders import seed_minimal_order

pytestmark = pytest.mark.integration


async def _admin(session: AsyncSession, *, role: str = "super_admin") -> AdminUser:
    a = AdminUser(
        email=f"audit-{secrets.token_hex(4)}@pharmacy.kg",
        password_hash="x" * 60,
        first_name="Audit",
        last_name="Test",
        role=role,
        is_active=True,
    )
    session.add(a)
    await session.flush()
    return a


async def _audit_count(session: AsyncSession) -> int:
    return int((await session.execute(select(func.count(AdminAuditLog.id)))).scalar_one())


# ─── Phase 5 — catalog ───────────────────────────────────────────────────────


async def test_catalog_create_manufacturer_writes_audit(
    session: AsyncSession, redis_clean: None
) -> None:
    actor = await _admin(session)
    svc = CatalogAdminService(
        manufacturers=ManufacturerRepository(session),
        ingredients=ActiveIngredientRepository(session),
        categories=CategoryRepository(session),
        symptoms=SymptomRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )
    before = await _audit_count(session)
    await svc.create_manufacturer(
        payload=ManufacturerCreate(name=f"AC-{secrets.token_hex(4)}"),
        actor=actor,
    )
    after = await _audit_count(session)
    assert after == before + 1


async def test_catalog_create_category_writes_audit(
    session: AsyncSession, redis_clean: None
) -> None:
    actor = await _admin(session)
    svc = CatalogAdminService(
        manufacturers=ManufacturerRepository(session),
        ingredients=ActiveIngredientRepository(session),
        categories=CategoryRepository(session),
        symptoms=SymptomRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )
    before = await _audit_count(session)
    await svc.create_category(
        payload=CategoryCreate(
            translations=[CategoryTranslationIn(language_code="ru", name="Аудит-кат")]
        ),
        actor=actor,
    )
    after = await _audit_count(session)
    assert after == before + 1


# ─── Phase 6 — inventory ─────────────────────────────────────────────────────


async def test_inventory_receive_batch_writes_audit(
    session: AsyncSession, redis_clean: None
) -> None:
    actor = await _admin(session)
    branch = await seed_branch(session, code=f"AU-{secrets.token_hex(3)}")
    cat = await seed_category(session, slug=f"au-{secrets.token_hex(3)}")
    p = await seed_product(
        session,
        sku=f"AU-{secrets.token_hex(3)}",
        slug=f"au-{secrets.token_hex(3)}",
        category_id=cat.id,
    )
    inv = InventoryService(
        session=session,
        branches=BranchRepository(session),
        suppliers=SupplierRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        movements=StockMovementRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )
    before = await _audit_count(session)
    await inv.receive_batch(
        branch_id=branch.id,
        payload=BatchReceiveRequest(
            product_id=p.id,
            batch_number=f"AU-LOT-{secrets.token_hex(3)}",
            expiry_date=date.today() + timedelta(days=365),
            quantity_received=10,
            cost_price=Decimal("50"),
        ),
        actor=actor,
    )
    after = await _audit_count(session)
    assert after == before + 1


async def test_inventory_adjust_batch_writes_audit(
    session: AsyncSession, redis_clean: None
) -> None:
    actor = await _admin(session)
    branch = await seed_branch(session, code=f"AUA-{secrets.token_hex(3)}")
    cat = await seed_category(session, slug=f"aua-{secrets.token_hex(3)}")
    p = await seed_product(
        session,
        sku=f"AUA-{secrets.token_hex(3)}",
        slug=f"aua-{secrets.token_hex(3)}",
        category_id=cat.id,
    )
    await seed_branch_product(session, branch_id=branch.id, product_id=p.id, total_quantity=10)
    batch = await seed_inventory_batch(
        session,
        branch_id=branch.id,
        product_id=p.id,
        batch_number=f"AUA-LOT-{secrets.token_hex(3)}",
    )
    inv = InventoryService(
        session=session,
        branches=BranchRepository(session),
        suppliers=SupplierRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        movements=StockMovementRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )
    before = await _audit_count(session)
    await inv.adjust_batch(
        batch.id,
        payload=BatchAdjustRequest(quantity_change=-2, movement_type="damaged", reason="dropped"),
        actor=actor,
    )
    after = await _audit_count(session)
    assert after == before + 1


# ─── Phase 9 — order lifecycle ───────────────────────────────────────────────


async def test_lifecycle_confirm_writes_audit(session: AsyncSession, redis_clean: None) -> None:
    actor = await _admin(session)
    branch = await seed_branch(session, code=f"AUL-{secrets.token_hex(3)}")
    order = await seed_minimal_order(session, branch_id=branch.id)

    svc = OrderLifecycleService(
        session=session,
        orders=OrderRepository(session),
        order_history=OrderStatusHistoryRepository(session),
        batches=InventoryBatchRepository(session),
        branch_products=BranchProductRepository(session),
        movements=StockMovementRepository(session),
        inventory=InventoryService(
            session=session,
            branches=BranchRepository(session),
            suppliers=SupplierRepository(session),
            branch_products=BranchProductRepository(session),
            batches=InventoryBatchRepository(session),
            movements=StockMovementRepository(session),
            audit=AdminAuditLogService(AdminAuditLogRepository(session)),
        ),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )
    before = await _audit_count(session)
    await svc.confirm(order.id, actor=actor)
    after = await _audit_count(session)
    assert after == before + 1

"""Storefront cache invalidation tests.

Covers:
* Categories tree is cached and invalidates on category mutation.
* Product detail is cached and invalidates on product update +
  branch_product update (Phase 6 inventory pricing).

These run against the real DB and the real Redis; the ``redis_clean``
fixture flushes between tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import invalidate as cache_invalidate
from app.core.redis import get_redis
from app.domain.catalog.repositories import (
    CategoryRepository,
    ProductRepository,
    SymptomRepository,
)
from app.domain.catalog.schemas import (
    CategoryCreate,
    CategoryTranslationIn,
)
from app.domain.catalog.services import CatalogAdminService
from app.domain.catalog.storefront import (
    StorefrontCatalogService,
    category_tree_key,
    product_detail_key,
)
from app.domain.identity.models import AdminUser
from app.domain.inventory.repositories import (
    BranchProductRepository,
    BranchRepository,
    InventoryBatchRepository,
    StockMovementRepository,
    SupplierRepository,
)
from app.domain.inventory.schemas import BranchProductUpdate
from app.domain.inventory.services import InventoryService
from app.domain.ops.repositories import AdminAuditLogRepository
from app.domain.ops.services import AdminAuditLogService
from tests.factories.catalog import (
    seed_category,
    seed_manufacturer,
    seed_product,
)
from tests.factories.inventory import seed_branch, seed_branch_product

pytestmark = pytest.mark.unit


def _storefront(session: AsyncSession) -> StorefrontCatalogService:
    return StorefrontCatalogService(
        categories=CategoryRepository(session),
        products=ProductRepository(session),
        symptoms=SymptomRepository(session),
        branches=BranchRepository(session),
    )


async def _make_actor(session: AsyncSession, *, suffix: str) -> AdminUser:
    admin = AdminUser(
        email=f"cache-{suffix}@pharmacy.kg",
        password_hash="x" * 60,
        first_name="Cache",
        last_name="Actor",
        role="super_admin",
        is_active=True,
    )
    session.add(admin)
    await session.flush()
    return admin


# ─── Categories tree cache ───────────────────────────────────────────────────


async def test_categories_tree_caches_then_invalidates(
    session: AsyncSession, redis_clean: None
) -> None:
    storefront = _storefront(session)
    await seed_category(session, slug="cache-cat-1", name_ru="Кэш Кат 1")
    await session.commit()

    # First call — DB; result lands in Redis.
    first = await storefront.get_categories_tree(language_code="ru")
    assert any(n.slug == "cache-cat-1" for n in first)

    r = get_redis()
    assert await r.get(category_tree_key("ru")) is not None

    # Mutate — invalidates.
    svc = CatalogAdminService(
        manufacturers=None,  # type: ignore[arg-type]
        ingredients=None,  # type: ignore[arg-type]
        categories=CategoryRepository(session),
        symptoms=None,  # type: ignore[arg-type]
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )
    actor = await _make_actor(session, suffix="cat-inv")
    await svc.create_category(
        payload=CategoryCreate(
            translations=[CategoryTranslationIn(language_code="ru", name="Новая категория")]
        ),
        actor=actor,
    )
    # Invalidation runs inside the service.
    assert await r.get(category_tree_key("ru")) is None


# ─── Product detail cache ────────────────────────────────────────────────────


async def test_product_detail_invalidates_on_branch_product_update(
    session: AsyncSession, redis_clean: None
) -> None:
    cat = await seed_category(session, slug="cache-prod-cat")
    mfr = await seed_manufacturer(session, name="CacheMfr")
    prod = await seed_product(
        session,
        sku="CACHE-PROD-1",
        slug="cache-prod-1",
        category_id=cat.id,
        manufacturer_id=mfr.id,
    )
    branch = await seed_branch(session, code="CACHE-BR-1")
    await seed_branch_product(
        session,
        branch_id=branch.id,
        product_id=prod.id,
        price=Decimal("100"),
        total_quantity=10,
    )
    await session.commit()

    # Manually warm the cache key (the storefront detail loader needs
    # a real read path; simulate the post-load state here).
    r = get_redis()
    await r.set(product_detail_key(prod.slug, "ru"), b'{"warm":1}', ex=300)
    assert await r.get(product_detail_key(prod.slug, "ru")) is not None

    # Update price via inventory service — should invalidate.
    inv = InventoryService(
        session=session,
        branches=BranchRepository(session),
        suppliers=SupplierRepository(session),
        branch_products=BranchProductRepository(session),
        batches=InventoryBatchRepository(session),
        movements=StockMovementRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )
    actor = await _make_actor(session, suffix="bp-inv")
    await inv.update_branch_product(
        branch_id=branch.id,
        product_id=prod.id,
        payload=BranchProductUpdate(price=Decimal("200")),
        actor=actor,
    )
    assert await r.get(product_detail_key(prod.slug, "ru")) is None


# ─── Smoke: cache_invalidate is no-op when Redis missing ─────────────────────


async def test_invalidate_noop_without_redis(monkeypatch) -> None:
    """``cache_invalidate`` returns 0 when Redis isn't initialised — used
    by unit tests that exercise services without a Redis client.
    """
    from app.core import redis as redis_module

    original = redis_module._redis  # type: ignore[attr-defined]
    redis_module._redis = None  # type: ignore[attr-defined]
    try:
        deleted = await cache_invalidate("nonexistent:")
        assert deleted == 0
    finally:
        redis_module._redis = original  # type: ignore[attr-defined]

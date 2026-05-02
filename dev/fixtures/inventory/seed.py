"""Seed branches, suppliers, branch_products, and inventory_batches.

Idempotent: skips rows whose unique key already exists. Safe to re-run.
Depends on the catalog seed having been run first (it resolves products
by SKU). Run the catalog seed too if products are missing.

Usage::

    uv run python -m dev.fixtures.catalog.seed
    uv run python -m dev.fixtures.inventory.seed
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.domain.catalog.models import Product
from app.domain.inventory.models import (
    Branch,
    BranchProduct,
    InventoryBatch,
    MovementType,
    StockMovement,
    Supplier,
)
from app.domain.inventory.repositories import (
    BranchProductRepository,
    BranchRepository,
    InventoryBatchRepository,
    SupplierRepository,
)

_HERE = Path(__file__).parent


def _load(name: str) -> list[dict[str, Any]]:
    return json.loads((_HERE / name).read_text())


async def _seed_branches(session: Any) -> dict[str, int]:
    repo = BranchRepository(session)
    out: dict[str, int] = {}
    for row in _load("branches.json"):
        if (existing := await repo.get_by_code(row["code"])) is not None:
            out[row["code"]] = existing.id
            continue
        b = Branch(
            code=row["code"],
            name=row["name"],
            address=row["address"],
            city=row.get("city", "Bishkek"),
            phone=row.get("phone"),
            timezone=row.get("timezone", "Asia/Bishkek"),
            is_active=True,
        )
        session.add(b)
        await session.flush()
        out[row["code"]] = b.id
    return out


async def _seed_suppliers(session: Any) -> dict[str, int]:
    repo = SupplierRepository(session)
    out: dict[str, int] = {}
    for row in _load("suppliers.json"):
        if (existing := await repo.get_by_name(row["name"])) is not None:
            out[row["name"]] = existing.id
            continue
        s = Supplier(
            name=row["name"],
            contact_phone=row.get("contact_phone"),
            contact_email=row.get("contact_email"),
            address=row.get("address"),
            is_active=True,
        )
        session.add(s)
        await session.flush()
        out[row["name"]] = s.id
    return out


async def _resolve_product_by_sku(session: Any, sku: str) -> Product | None:
    return (await session.execute(select(Product).where(Product.sku == sku))).scalar_one_or_none()


async def _seed_batches(
    session: Any,
    *,
    branches: dict[str, int],
    suppliers: dict[str, int],
) -> tuple[int, int]:
    """Returns (n_branch_products_created, n_batches_created)."""
    bp_repo = BranchProductRepository(session)
    batch_repo = InventoryBatchRepository(session)
    n_bp = 0
    n_batches = 0
    today = date.today()

    for row in _load("batches.json"):
        product = await _resolve_product_by_sku(session, row["product_sku"])
        if product is None:
            print(f"  skip — product '{row['product_sku']}' not in catalog")
            continue
        branch_id = branches[row["branch_code"]]

        # Get/create branch_products row.
        bp = await bp_repo.get(branch_id, product.id)
        if bp is None:
            bp = BranchProduct(
                branch_id=branch_id,
                product_id=product.id,
                price=Decimal(row["branch_product_price"]),
                currency="KGS",
                is_available=True,
                total_quantity=0,
                reserved_quantity=0,
                low_stock_threshold=10,
            )
            await bp_repo.add(bp)
            n_bp += 1
        elif bp.price == 0:
            # Auto-created from a prior receive at price=0; promote.
            bp.price = Decimal(row["branch_product_price"])
            bp.is_available = True
            await session.flush()

        # Add the batch (skip if batch_number already exists for this pair).
        existing = await batch_repo.get_by_natural_key(
            branch_id=branch_id,
            product_id=product.id,
            batch_number=row["batch_number"],
        )
        if existing is not None:
            continue

        batch = InventoryBatch(
            branch_id=branch_id,
            product_id=product.id,
            supplier_id=suppliers.get(row["supplier_name"]),
            batch_number=row["batch_number"],
            expiry_date=today + timedelta(days=row["expiry_days_from_today"]),
            manufacture_date=today - timedelta(days=row["manufacture_days_ago"]),
            quantity_received=row["quantity_received"],
            quantity_remaining=row["quantity_received"],
            quantity_reserved=0,
            cost_price=Decimal(row["cost_price"]),
            currency="KGS",
        )
        await batch_repo.add(batch)
        bp.total_quantity += row["quantity_received"]
        # Pair the cache update with a stock_movements row for audit
        # parity with the live receive_batch service path.
        session.add(
            StockMovement(
                inventory_batch_id=batch.id,
                branch_id=branch_id,
                product_id=product.id,
                movement_type=MovementType.RECEIVED.value,
                quantity_change=row["quantity_received"],
                quantity_after=batch.quantity_remaining,
                admin_user_id=None,
                reason="dev-fixture seed",
            )
        )
        await session.flush()
        n_batches += 1

    return (n_bp, n_batches)


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            branches = await _seed_branches(session)
            suppliers = await _seed_suppliers(session)
            n_bp, n_batches = await _seed_batches(session, branches=branches, suppliers=suppliers)
            await session.commit()
            print(
                f"Seeded {len(branches)} branches, {len(suppliers)} suppliers, "
                f"{n_bp} branch_products, {n_batches} inventory_batches."
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

"""Inventory factories — in-session and committed seeders.

Mirror of :mod:`tests.factories.catalog`.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.domain.inventory.models import (
    Branch,
    BranchProduct,
    InventoryBatch,
    Supplier,
)

# ─── In-session seeders ──────────────────────────────────────────────────────


async def seed_branch(
    session: AsyncSession,
    *,
    code: str,
    name: str = "Тестовая аптека",
    address: str = "мкр Асанбай, 12",
    is_active: bool = True,
) -> Branch:
    b = Branch(code=code, name=name, address=address, is_active=is_active)
    session.add(b)
    await session.flush()
    return b


async def seed_supplier(session: AsyncSession, *, name: str) -> Supplier:
    s = Supplier(name=name, is_active=True)
    session.add(s)
    await session.flush()
    return s


async def seed_branch_product(
    session: AsyncSession,
    *,
    branch_id: int,
    product_id: UUID,
    price: Decimal | str = "100.00",
    is_available: bool = True,
    total_quantity: int = 0,
    reserved_quantity: int = 0,
    low_stock_threshold: int = 10,
) -> BranchProduct:
    bp = BranchProduct(
        branch_id=branch_id,
        product_id=product_id,
        price=Decimal(price) if isinstance(price, str) else price,
        currency="KGS",
        is_available=is_available,
        total_quantity=total_quantity,
        reserved_quantity=reserved_quantity,
        low_stock_threshold=low_stock_threshold,
    )
    session.add(bp)
    await session.flush()
    return bp


async def seed_inventory_batch(
    session: AsyncSession,
    *,
    branch_id: int,
    product_id: UUID,
    batch_number: str,
    expiry_date: date | None = None,
    quantity_received: int = 100,
    quantity_remaining: int | None = None,
    quantity_reserved: int = 0,
    cost_price: Decimal | str = "50.00",
    supplier_id: int | None = None,
) -> InventoryBatch:
    if expiry_date is None:
        expiry_date = date.today() + timedelta(days=365)
    if quantity_remaining is None:
        quantity_remaining = quantity_received
    batch = InventoryBatch(
        branch_id=branch_id,
        product_id=product_id,
        supplier_id=supplier_id,
        batch_number=batch_number,
        expiry_date=expiry_date,
        quantity_received=quantity_received,
        quantity_remaining=quantity_remaining,
        quantity_reserved=quantity_reserved,
        cost_price=Decimal(cost_price) if isinstance(cost_price, str) else cost_price,
        currency="KGS",
    )
    session.add(batch)
    await session.flush()
    return batch


# ─── Committed seeders for E2E ───────────────────────────────────────────────


async def seed_branch_committed(*, code: str, name: str = "Тестовая аптека") -> int:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            b = Branch(code=code, name=name, address="мкр Асанбай 12", is_active=True)
            s.add(b)
            await s.commit()
            assert b.id is not None
            return b.id
    finally:
        await engine.dispose()


async def seed_branch_product_committed(
    *,
    branch_id: int,
    product_id: UUID,
    price: str = "100.00",
    total_quantity: int = 0,
    low_stock_threshold: int = 10,
    is_available: bool = True,
) -> None:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as s:
            bp = BranchProduct(
                branch_id=branch_id,
                product_id=product_id,
                price=Decimal(price),
                currency="KGS",
                is_available=is_available,
                total_quantity=total_quantity,
                reserved_quantity=0,
                low_stock_threshold=low_stock_threshold,
            )
            s.add(bp)
            await s.commit()
    finally:
        await engine.dispose()


async def seed_inventory_batch_committed(
    *,
    branch_id: int,
    product_id: UUID,
    batch_number: str,
    expiry_date: date | None = None,
    quantity_received: int = 100,
) -> int:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    if expiry_date is None:
        expiry_date = date.today() + timedelta(days=365)
    try:
        async with factory() as s:
            batch = InventoryBatch(
                branch_id=branch_id,
                product_id=product_id,
                batch_number=batch_number,
                expiry_date=expiry_date,
                quantity_received=quantity_received,
                quantity_remaining=quantity_received,
                quantity_reserved=0,
                cost_price=Decimal("50.00"),
                currency="KGS",
            )
            s.add(batch)
            await s.commit()
            assert batch.id is not None
            return batch.id
    finally:
        await engine.dispose()

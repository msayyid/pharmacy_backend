"""E2E — admin reports + audit-log viewer."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.types import uuid7
from app.domain.identity.models import User
from app.domain.inventory.models import Branch
from app.domain.orders.models import Order, OrderItem, OrderStatus
from tests.e2e.conftest import seed_admin_committed

pytestmark = pytest.mark.e2e


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@pharmacy.kg"


async def _seed_orders_for_report() -> dict:
    settings = get_settings()
    engine = create_async_engine(str(settings.mysql_dsn), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    out: dict = {}
    today = datetime.now(tz=UTC).replace(tzinfo=None)
    try:
        async with factory() as s:
            branch = Branch(
                code=f"RPT-{secrets.token_hex(4).upper()}",
                name="Report Test",
                address="мкр Асанбай 12",
                is_active=True,
            )
            s.add(branch)
            await s.flush()
            out["branch_id"] = branch.id
            out["from_dt"] = (today - timedelta(days=1)).isoformat()
            out["to_dt"] = (today + timedelta(hours=1)).isoformat()

            user = User(
                id=uuid7(),
                phone=f"+99670{secrets.randbelow(10**6):07d}",
                preferred_language="ru",
                is_phone_verified=True,
                is_active=True,
            )
            s.add(user)
            await s.flush()

            order = Order(
                id=uuid7(),
                order_number=f"PH-RPT-{secrets.token_hex(6).upper()}",
                user_id=user.id,
                branch_id=branch.id,
                status=OrderStatus.DELIVERED.value,
                payment_status="paid",
                payment_method="cash_on_delivery",
                delivery_method="pickup",
                recipient_name="Test",
                recipient_phone="+996700000000",
                subtotal=Decimal("500"),
                delivery_fee=Decimal("0"),
                discount_amount=Decimal("0"),
                total=Decimal("500"),
                currency="KGS",
                placed_at=today,
            )
            s.add(order)
            await s.flush()
            s.add(
                OrderItem(
                    order_id=order.id,
                    product_id=None,
                    inventory_batch_id=None,
                    product_name_snapshot="Test-Item",
                    product_sku_snapshot="TEST-1",
                    quantity=5,
                    unit_price=Decimal("100"),
                    line_total=Decimal("500"),
                )
            )
            await s.commit()
        return out
    finally:
        await engine.dispose()


async def _login_admin(client: AsyncClient, *, role: str = "super_admin") -> dict[str, str]:
    email = _email(role)
    await seed_admin_committed(email=email, password="ok", role=role)
    r = await client.post(
        "/api/admin/v1/auth/login",
        json={"email": email, "password": "ok"},
    )
    assert r.status_code == 200, r.text
    return {"admin_session": r.cookies["admin_session"]}


# ─── Sales report ────────────────────────────────────────────────────────────


async def test_sales_report_json(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_orders_for_report()
    cookies = await _login_admin(client)

    r = await client.get(
        "/api/admin/v1/reports/sales",
        params={
            "from": seed["from_dt"],
            "to": seed["to_dt"],
            "branch": seed["branch_id"],
        },
        cookies=cookies,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "summary" in body
    s = body["summary"]
    assert Decimal(s["revenue"]) >= Decimal("500")
    assert s["units"] >= 5


async def test_sales_report_csv(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_orders_for_report()
    cookies = await _login_admin(client)

    r = await client.get(
        "/api/admin/v1/reports/sales",
        params={
            "from": seed["from_dt"],
            "to": seed["to_dt"],
            "branch": seed["branch_id"],
            "format": "csv",
        },
        cookies=cookies,
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    body = r.text
    # BOM + header
    assert "kind,revenue,units" in body
    assert "summary," in body


async def test_top_products_report(client: AsyncClient, redis_clean: None) -> None:
    seed = await _seed_orders_for_report()
    cookies = await _login_admin(client)

    r = await client.get(
        "/api/admin/v1/reports/top-products",
        params={
            "from": seed["from_dt"],
            "to": seed["to_dt"],
            "branch": seed["branch_id"],
            "limit": 5,
        },
        cookies=cookies,
    )
    assert r.status_code == 200
    body = r.json()
    assert "items" in body


# ─── Audit viewer ────────────────────────────────────────────────────────────


async def test_audit_viewer_lists_recent_rows(client: AsyncClient, redis_clean: None) -> None:
    cookies = await _login_admin(client)
    r = await client.get("/api/admin/v1/audit", cookies=cookies)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body

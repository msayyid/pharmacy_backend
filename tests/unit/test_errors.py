"""Error hierarchy and Problem Details handler tests."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.core.errors import (
    AppError,
    ConflictError,
    InvalidOTPError,
    OutOfStockError,
    RateLimitExceededError,
    ValidationError,
)


def test_app_error_default_message() -> None:
    e = AppError()
    assert e.code == "internal_error"
    assert e.status_code == 500
    assert str(e) == "Internal error"
    assert e.context == {}


def test_app_error_carries_context() -> None:
    e = OutOfStockError("Item gone", product_id="abc", requested=5, available=2)
    assert e.code == "out_of_stock"
    assert e.status_code == 409
    assert str(e) == "Item gone"
    assert e.context == {"product_id": "abc", "requested": 5, "available": 2}


def test_subclasses_inherit_status_codes() -> None:
    assert ValidationError().status_code == 400
    assert ConflictError().status_code == 409
    assert RateLimitExceededError().status_code == 429
    assert OutOfStockError().status_code == 409
    assert InvalidOTPError().status_code == 401


async def test_app_error_renders_problem_details() -> None:
    """A raised AppError surfaces as RFC 7807 Problem Details JSON."""
    from app.main import create_app

    app = create_app()

    @app.get("/_test/oos")
    async def _oos() -> dict[str, str]:
        raise OutOfStockError("Item gone", product_id="x", requested=1, available=0)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/_test/oos")

    assert r.status_code == 409
    body = r.json()
    assert body["status"] == 409
    assert body["code"] == "out_of_stock"
    assert body["type"] == "about:blank#out_of_stock"
    assert body["title"] == "Conflict"
    assert "detail" in body
    assert body["context"] == {"product_id": "x", "requested": 1, "available": 0}


async def test_validation_error_handler_returns_422() -> None:
    """Pydantic RequestValidationError → 422 + validation_error code."""
    from pydantic import BaseModel

    from app.main import create_app

    app = create_app()

    class _In(BaseModel):
        n: int

    @app.post("/_test/validate")
    async def _v(payload: _In) -> dict[str, int]:
        return {"n": payload.n}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/_test/validate", json={"n": "not-a-number"})

    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert body["status"] == 422
    assert "errors" in body

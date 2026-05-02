"""Idempotency-key store — miss / hit_same / hit_different."""

from __future__ import annotations

import pytest

from app.core.idempotency import body_digest, check, store

pytestmark = pytest.mark.integration


async def test_check_returns_miss_when_key_absent(redis_clean: None) -> None:
    result, payload = await check("idem-1", "digest-X")
    assert result == "miss"
    assert payload is None


async def test_store_then_check_returns_hit_same(redis_clean: None) -> None:
    digest = body_digest('{"foo":"bar"}')
    await store("idem-1", digest, {"order_number": "PH-2026-000001"})
    result, payload = await check("idem-1", digest)
    assert result == "hit_same"
    assert payload == {"order_number": "PH-2026-000001"}


async def test_check_with_different_digest_returns_hit_different(redis_clean: None) -> None:
    """Same Idempotency-Key but different request body → conflict signal."""
    await store("idem-1", "digest-A", {"order_number": "PH-001"})
    result, payload = await check("idem-1", "digest-B")
    assert result == "hit_different"
    assert payload is None


async def test_scope_isolates_keys(redis_clean: None) -> None:
    """The same idempotency-key in different scopes is independent."""
    await store("idem-1", "digest-X", {"v": 1}, scope="checkout")
    result, _ = await check("idem-1", "digest-X", scope="refund")
    assert result == "miss"
    result2, payload = await check("idem-1", "digest-X", scope="checkout")
    assert result2 == "hit_same"
    assert payload == {"v": 1}


def test_body_digest_is_stable() -> None:
    assert body_digest('{"foo":"bar"}') == body_digest('{"foo":"bar"}')
    assert body_digest('{"foo":"bar"}') != body_digest('{"foo":"baz"}')


def test_body_digest_accepts_bytes_or_str() -> None:
    assert body_digest("hello") == body_digest(b"hello")

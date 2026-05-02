"""Idempotency-key store, backed by Redis with 24h TTL.

For POSTs that create money-relevant resources (place-order, refund), the
client sends ``Idempotency-Key: <uuid>``. The service:

1. Computes ``digest = sha256(method + path + body)``.
2. Calls :func:`check` against the stored entry under the same key.
3. ``"miss"`` → execute, then :func:`store` the response.
4. ``"hit_same"`` → return the stored response (idempotent replay).
5. ``"hit_different"`` → 409 conflict (key reused with a different body).

State is in Redis only — the OLTP DB stays lean. Default TTL: 24 hours.

Reference: BACKEND_BLUEPRINT.md §21.
"""

from __future__ import annotations

import hashlib
from typing import Any, Literal

import orjson

from app.core.cache import get_raw, set_raw

DEFAULT_TTL_SECONDS = 24 * 3600
_KEY_PREFIX = "v1:idem"

CheckResult = Literal["miss", "hit_same", "hit_different"]


def _make_key(idempotency_key: str, scope: str = "") -> str:
    """Compose a Redis key. ``scope`` lets routes namespace independently."""
    return (
        f"{_KEY_PREFIX}:{scope}:{idempotency_key}" if scope else f"{_KEY_PREFIX}:{idempotency_key}"
    )


def body_digest(body: bytes | str) -> str:
    """Hex SHA-256 of the request body (or any normalised representation)."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    return hashlib.sha256(body).hexdigest()


async def check(
    idempotency_key: str,
    digest: str,
    *,
    scope: str = "",
) -> tuple[CheckResult, dict[str, Any] | None]:
    """Inspect the stored entry. Returns ``(result, stored_response_or_None)``."""
    key = _make_key(idempotency_key, scope)
    raw = await get_raw(key)
    if raw is None:
        return ("miss", None)
    entry: dict[str, Any] = orjson.loads(raw)
    stored_digest: str = entry["digest"]
    response: dict[str, Any] = entry["response"]
    if stored_digest == digest:
        return ("hit_same", response)
    return ("hit_different", None)


async def store(
    idempotency_key: str,
    digest: str,
    response: dict[str, Any],
    *,
    scope: str = "",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> None:
    """Persist the digest + response payload under ``idempotency_key`` for ``ttl``."""
    key = _make_key(idempotency_key, scope)
    payload = orjson.dumps({"digest": digest, "response": response}).decode("utf-8")
    await set_raw(key, payload, ttl_seconds)

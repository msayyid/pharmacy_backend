"""Pagination helpers.

* **Offset paging** for catalog (cacheable, stable totals): ``PageParams``,
  ``page_params`` dependency, ``offset_limit``, ``Page[T]`` envelope.
* **Cursor paging** for append-mostly lists (orders, audit log):
  ``encode_cursor`` / ``decode_cursor`` over base64url JSON of
  ``(created_at, id)``; ``Cursor[T]`` envelope.
* **Sort parsing** with allow-list: ``parse_sort("name,-price", {"name","price"})``
  → ``[("name", False), ("price", True)]``.

Reference: BACKEND_BLUEPRINT.md §10.4, §20.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Annotated, Generic, TypeVar
from uuid import UUID

import orjson
from fastapi import Query
from pydantic import BaseModel, Field

from app.core.errors import ValidationError

T = TypeVar("T")


# ─── Offset paging ────────────────────────────────────────────────────────────


class PageParams(BaseModel):
    """Validated page request — clamped to ``page >= 1`` and ``1 <= page_size <= 100``."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=24, ge=1, le=100)


def page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> PageParams:
    """FastAPI dependency: ``page`` and ``page_size`` query params."""
    return PageParams(page=page, page_size=page_size)


def offset_limit(p: PageParams) -> tuple[int, int]:
    """Convert ``PageParams`` to ``(offset, limit)`` for SQL."""
    return ((p.page - 1) * p.page_size, p.page_size)


class Page(BaseModel, Generic[T]):
    """Standard envelope for offset-paginated list responses."""

    items: list[T]
    total: int | None = None
    page: int | None = None
    page_size: int | None = None


# ─── Cursor paging ────────────────────────────────────────────────────────────


class Cursor(BaseModel, Generic[T]):
    """Standard envelope for cursor-paginated list responses."""

    items: list[T]
    next_cursor: str | None = None


class CursorParams(BaseModel):
    """Decoded cursor — pointer to the last seen ``(created_at, id)`` tuple."""

    created_at: datetime
    id: str  # opaque — UUID or BIGINT as str


def encode_cursor(created_at: datetime, item_id: UUID | int | str) -> str:
    """Encode a ``(created_at, id)`` pair to a base64url string."""
    payload = {"created_at": created_at.isoformat(), "id": str(item_id)}
    raw = orjson.dumps(payload)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> CursorParams:
    """Decode a cursor token. Raises :class:`ValidationError` on malformed input."""
    if not token:
        raise ValidationError("cursor_empty")
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode((token + padding).encode("ascii"))
        payload = orjson.loads(raw)
        return CursorParams(
            created_at=datetime.fromisoformat(payload["created_at"]),
            id=payload["id"],
        )
    except (ValueError, KeyError, TypeError) as e:
        raise ValidationError(f"cursor_invalid: {e}") from e


# ─── Sort parsing (allow-list) ────────────────────────────────────────────────


def parse_sort(value: str | None, allowed: set[str]) -> list[tuple[str, bool]]:
    """Parse a sort string like ``"name,-price"`` into ``[(field, desc), ...]``.

    Each field must be in ``allowed`` or :class:`ValidationError` is raised.
    Direction prefix: ``-`` → descending; nothing or ``+`` → ascending.
    """
    if not value:
        return []
    out: list[tuple[str, bool]] = []
    for raw in value.split(","):
        token = raw.strip()
        if not token:
            continue
        desc = token.startswith("-")
        field = token.lstrip("-+")
        if field not in allowed:
            raise ValidationError(f"sort_not_allowed: {field}", field=field)
        out.append((field, desc))
    return out

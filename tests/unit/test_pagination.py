"""Pagination — PageParams clamping, sort allow-list, cursor encode/decode."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError
from app.core.pagination import (
    PageParams,
    decode_cursor,
    encode_cursor,
    offset_limit,
    parse_sort,
)

# ─── PageParams ───────────────────────────────────────────────────────────────


def test_page_params_defaults() -> None:
    p = PageParams()
    assert p.page == 1
    assert p.page_size == 24


def test_page_params_rejects_zero_page() -> None:
    with pytest.raises(PydanticValidationError):
        PageParams(page=0)


def test_page_params_rejects_zero_page_size() -> None:
    with pytest.raises(PydanticValidationError):
        PageParams(page_size=0)


def test_page_params_rejects_oversized_page_size() -> None:
    with pytest.raises(PydanticValidationError):
        PageParams(page_size=101)


def test_offset_limit_for_typical_pages() -> None:
    assert offset_limit(PageParams(page=1, page_size=24)) == (0, 24)
    assert offset_limit(PageParams(page=2, page_size=24)) == (24, 24)
    assert offset_limit(PageParams(page=10, page_size=10)) == (90, 10)


# ─── Sort ─────────────────────────────────────────────────────────────────────


def test_parse_sort_simple_ascending() -> None:
    assert parse_sort("name", {"name", "price"}) == [("name", False)]


def test_parse_sort_explicit_descending() -> None:
    assert parse_sort("-price", {"name", "price"}) == [("price", True)]


def test_parse_sort_multi_field() -> None:
    assert parse_sort("name,-price", {"name", "price"}) == [
        ("name", False),
        ("price", True),
    ]


def test_parse_sort_empty_returns_empty() -> None:
    assert parse_sort(None, {"name"}) == []
    assert parse_sort("", {"name"}) == []


def test_parse_sort_rejects_unallowed_field() -> None:
    with pytest.raises(ValidationError):
        parse_sort("forbidden", {"name", "price"})


def test_parse_sort_strips_whitespace() -> None:
    assert parse_sort(" name , -price ", {"name", "price"}) == [
        ("name", False),
        ("price", True),
    ]


# ─── Cursor ───────────────────────────────────────────────────────────────────


def test_cursor_round_trip_string_id() -> None:
    now = datetime.now(UTC)
    token = encode_cursor(now, "01999999-1234-5678-9abc-def012345678")
    back = decode_cursor(token)
    assert back.created_at == now
    assert back.id == "01999999-1234-5678-9abc-def012345678"


def test_cursor_round_trip_int_id_stringifies() -> None:
    now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    token = encode_cursor(now, 42)
    back = decode_cursor(token)
    assert back.id == "42"


def test_cursor_decode_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        decode_cursor("")


def test_cursor_decode_rejects_garbage() -> None:
    with pytest.raises(ValidationError):
        decode_cursor("!!!not-base64-at-all!!!")

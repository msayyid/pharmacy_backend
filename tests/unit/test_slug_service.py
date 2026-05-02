"""Unit tests for slug helpers in :mod:`app.domain.catalog.slug`."""

from __future__ import annotations

import pytest

from app.domain.catalog.slug import slugify_name, unique_slug

pytestmark = pytest.mark.unit


def test_slugify_name_transliterates_cyrillic() -> None:
    assert slugify_name("Парацетамол") == "paratsetamol"


def test_slugify_name_lowercases_and_hyphenates() -> None:
    assert slugify_name("Vitamin C 500mg") == "vitamin-c-500mg"


def test_slugify_name_strips_punctuation() -> None:
    assert slugify_name("Vitamin C+") == "vitamin-c"
    assert slugify_name("Tablets-100mg!") == "tablets-100mg"
    assert slugify_name("   Spaces   ") == "spaces"


def test_slugify_name_empty_returns_empty() -> None:
    assert slugify_name("") == ""
    assert slugify_name("   ") == ""


async def test_unique_slug_returns_base_when_unused() -> None:
    async def _exists(_s: str) -> bool:
        return False

    assert await unique_slug("paracetamol", _exists) == "paracetamol"


async def test_unique_slug_appends_2_when_taken() -> None:
    async def _exists(s: str) -> bool:
        return s == "paracetamol"

    assert await unique_slug("paracetamol", _exists) == "paracetamol-2"


async def test_unique_slug_increments_until_free() -> None:
    taken = {"paracetamol", "paracetamol-2", "paracetamol-3"}

    async def _exists(s: str) -> bool:
        return s in taken

    assert await unique_slug("paracetamol", _exists) == "paracetamol-4"

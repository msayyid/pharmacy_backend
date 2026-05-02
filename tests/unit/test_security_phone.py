"""Phone normalisation — parse to E.164 with KG as default region."""

from __future__ import annotations

import pytest

from app.core.security import normalise_phone


def test_normalise_with_country_code() -> None:
    assert normalise_phone("+996700123456") == "+996700123456"
    assert normalise_phone("+996 700 12 34 56") == "+996700123456"


def test_normalise_local_with_default_kg() -> None:
    """Local form ``0700123456`` parses to E.164 with KG default region."""
    assert normalise_phone("0700123456") == "+996700123456"


def test_normalise_strips_separators() -> None:
    """Spaces, dashes, parentheses removed during parsing."""
    assert normalise_phone("+996-700-12-34-56") == "+996700123456"
    assert normalise_phone("+996 (700) 12-34-56") == "+996700123456"


def test_normalise_handles_kg_mobile_prefixes() -> None:
    """KG mobile prefixes per PRODUCT §16.5."""
    for prefix in ("700", "770", "550", "778", "558"):
        assert normalise_phone(f"+996{prefix}123456") == f"+996{prefix}123456"


def test_normalise_rejects_invalid_strings() -> None:
    for invalid in ("not-a-phone", "abc", ""):
        with pytest.raises(ValueError):
            normalise_phone(invalid)


def test_normalise_rejects_too_short() -> None:
    """A 4-digit number is not a valid international phone."""
    with pytest.raises(ValueError):
        normalise_phone("+1234")


def test_normalise_local_with_non_kg_region_rejects_kg_local() -> None:
    """When default region overrides KG, a local KG number stops parsing as +996."""
    with pytest.raises(ValueError):
        # 0700123456 is only meaningful in KG; in US default region it's invalid
        normalise_phone("0700123456", default_region="US")

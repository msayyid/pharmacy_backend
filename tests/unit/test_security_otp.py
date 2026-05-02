"""OTP — generate, hash, verify, length / pepper edge cases."""

from __future__ import annotations

import string

import pytest

from app.core.security import generate_numeric_code, hash_otp, verify_otp


def test_generate_numeric_code_produces_n_digits() -> None:
    for n in (4, 6, 8):
        code = generate_numeric_code(n)
        assert len(code) == n
        assert all(c in string.digits for c in code)


def test_generate_numeric_code_invalid_length() -> None:
    with pytest.raises(ValueError):
        generate_numeric_code(0)
    with pytest.raises(ValueError):
        generate_numeric_code(-1)


def test_generate_numeric_code_high_entropy() -> None:
    """100 codes shouldn't all be identical (sanity check on randomness)."""
    seen = {generate_numeric_code(6) for _ in range(100)}
    assert len(seen) > 50  # very loose lower bound


def test_otp_hash_verify_round_trip() -> None:
    h = hash_otp("123456", "pep")
    assert verify_otp("123456", h, "pep")


def test_otp_wrong_code_fails() -> None:
    h = hash_otp("123456", "pep")
    assert not verify_otp("000000", h, "pep")


def test_otp_wrong_pepper_fails() -> None:
    h = hash_otp("123456", "right-pepper")
    assert not verify_otp("123456", h, "wrong-pepper")


def test_otp_hash_is_64_char_hex() -> None:
    """SHA-256 produces 64-char hex output."""
    h = hash_otp("123456", "pep")
    assert len(h) == 64
    assert all(c in string.hexdigits.lower() for c in h)


def test_otp_hash_is_deterministic() -> None:
    """Same input + pepper always produces the same hash."""
    assert hash_otp("123456", "pep") == hash_otp("123456", "pep")

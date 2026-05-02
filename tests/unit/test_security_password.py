"""Password hashing — argon2id round-trip + tamper detection."""

from __future__ import annotations

from app.core.security import hash_password, verify_password


def test_password_hash_verify_round_trip() -> None:
    h = hash_password("hunter2", "pep")
    assert verify_password("hunter2", h, "pep")


def test_password_with_wrong_pepper_fails() -> None:
    h = hash_password("hunter2", "correct-pepper")
    assert not verify_password("hunter2", h, "wrong-pepper")


def test_password_with_wrong_password_fails() -> None:
    h = hash_password("right-password", "pep")
    assert not verify_password("wrong-password", h, "pep")


def test_password_hash_is_argon2id() -> None:
    """argon2id signature must appear in the hash."""
    h = hash_password("anything", "pep")
    assert h.startswith("$argon2id$")


def test_password_hash_uses_random_salt() -> None:
    """Same input + pepper produces different hashes due to random salt."""
    h1 = hash_password("same", "pep")
    h2 = hash_password("same", "pep")
    assert h1 != h2
    assert verify_password("same", h1, "pep")
    assert verify_password("same", h2, "pep")


def test_verify_against_garbage_hash_returns_false() -> None:
    """A malformed hash should return False, not raise."""
    assert not verify_password("password", "not-an-argon2-hash", "pep")


def test_password_hash_carries_configured_cost() -> None:
    """Cost params (m=65536, t=3, p=2) appear in the hash header."""
    h = hash_password("anything", "pep")
    assert "m=65536" in h
    assert "t=3" in h
    assert "p=2" in h

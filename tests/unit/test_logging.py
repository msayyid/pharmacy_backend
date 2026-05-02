"""Logging redaction and context-binding unit tests."""

from __future__ import annotations

from app.core.logging import (
    _ctx_processor,
    bind_context,
    clear_context,
    mask_phone,
    redact_pii,
)

# ─── mask_phone ───────────────────────────────────────────────────────────────


def test_mask_phone_e164_kg() -> None:
    assert mask_phone("+996700123456") == "+996****3456"
    assert mask_phone("+996770111234") == "+996****1234"
    assert mask_phone("+996550999888") == "+996****9888"


def test_mask_phone_too_short() -> None:
    assert mask_phone("123") == "<redacted>"
    assert mask_phone("") == "<redacted>"
    assert mask_phone("+99670") == "<redacted>"


# ─── redact_pii ───────────────────────────────────────────────────────────────


def test_redact_full_redact_fields() -> None:
    out = redact_pii(
        None,
        "info",
        {
            "password": "hunter2",
            "password_hash": "$argon2id$...",
            "code": "123456",
            "otp": "999999",
            "otp_code": "888888",
            "token": "ey...",
            "access_token": "ey-access...",
            "refresh_token": "rt...",
            "jwt": "eyJ...",
            "secret": "shh",
            "api_key": "key-...",
            "authorization": "Bearer xxx",
            "cookie": "sid=abc",
            "name": "Aizhana",  # NOT a sensitive field
        },
    )
    for k in (
        "password",
        "password_hash",
        "code",
        "otp",
        "otp_code",
        "token",
        "access_token",
        "refresh_token",
        "jwt",
        "secret",
        "api_key",
        "authorization",
        "cookie",
    ):
        assert out[k] == "<redacted>", f"{k} should be redacted"
    assert out["name"] == "Aizhana"


def test_redact_phone_fields_mask_partial() -> None:
    out = redact_pii(
        None,
        "info",
        {
            "phone": "+996700123456",
            "recipient_phone": "+996770111234",
            "courier_phone": "+996550999888",
            "contact_phone": "+996700987654",
            "name": "Marat",
        },
    )
    assert out["phone"] == "+996****3456"
    assert out["recipient_phone"] == "+996****1234"
    assert out["courier_phone"] == "+996****9888"
    assert out["contact_phone"] == "+996****7654"
    assert out["name"] == "Marat"


def test_redact_is_case_insensitive_on_field_names() -> None:
    out = redact_pii(None, "info", {"PASSWORD": "x", "Phone": "+996700123456"})
    assert out["PASSWORD"] == "<redacted>"
    assert out["Phone"] == "+996****3456"


# ─── context binding ──────────────────────────────────────────────────────────


def test_bind_context_propagates_to_event() -> None:
    bind_context(request_id="abc-123", user_id="u-1")
    try:
        out = _ctx_processor(None, "info", {"event": "anything"})
        assert out["request_id"] == "abc-123"
        assert out["user_id"] == "u-1"
        assert out["event"] == "anything"
    finally:
        clear_context()


def test_clear_context_removes_bound_fields() -> None:
    bind_context(request_id="rid-xyz")
    clear_context()
    out = _ctx_processor(None, "info", {"event": "after-clear"})
    assert "request_id" not in out


def test_event_does_not_overwrite_explicit_field() -> None:
    """If a log call explicitly sets ``request_id``, the context shouldn't override it."""
    bind_context(request_id="from-context")
    try:
        out = _ctx_processor(None, "info", {"request_id": "explicit"})
        assert out["request_id"] == "explicit"
    finally:
        clear_context()

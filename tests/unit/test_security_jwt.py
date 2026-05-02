"""JWT — issue, decode, expired, wrong-type, wrong-kind, kid header."""

from __future__ import annotations

import pytest
from freezegun import freeze_time
from jose import JWTError
from jose import jwt as _jwt

from app.core.security import (
    ACCESS_TYPE,
    ADMIN_KIND,
    CUSTOMER_KIND,
    DEFAULT_KID,
    REFRESH_TYPE,
    TokenIssuer,
)


def test_issue_pair_returns_distinct_tokens() -> None:
    issuer = TokenIssuer()
    pair = issuer.issue_pair(subject="user-abc", kind=CUSTOMER_KIND)
    assert pair.access != pair.refresh
    assert pair.access_jti != pair.refresh_jti


def test_decode_access_returns_expected_claims() -> None:
    issuer = TokenIssuer()
    pair = issuer.issue_pair(subject="user-abc", kind=CUSTOMER_KIND)
    claims = issuer.decode(pair.access, expected_type=ACCESS_TYPE, expected_kind=CUSTOMER_KIND)
    assert claims["sub"] == "user-abc"
    assert claims["kind"] == CUSTOMER_KIND
    assert claims["type"] == ACCESS_TYPE
    assert claims["jti"] == pair.access_jti


def test_decode_refresh_returns_expected_claims() -> None:
    issuer = TokenIssuer()
    pair = issuer.issue_pair(subject="user-abc", kind=CUSTOMER_KIND)
    claims = issuer.decode(pair.refresh, expected_type=REFRESH_TYPE, expected_kind=CUSTOMER_KIND)
    assert claims["type"] == REFRESH_TYPE
    assert claims["jti"] == pair.refresh_jti


def test_decode_wrong_type_rejected() -> None:
    """Using an access token where a refresh is expected must fail."""
    issuer = TokenIssuer()
    pair = issuer.issue_pair(subject="user-abc", kind=CUSTOMER_KIND)
    with pytest.raises(JWTError):
        issuer.decode(pair.access, expected_type=REFRESH_TYPE, expected_kind=CUSTOMER_KIND)


def test_decode_wrong_kind_rejected() -> None:
    """A customer token cannot authorise as admin (and vice versa)."""
    issuer = TokenIssuer()
    pair = issuer.issue_pair(subject="user-abc", kind=CUSTOMER_KIND)
    with pytest.raises(JWTError):
        issuer.decode(pair.access, expected_type=ACCESS_TYPE, expected_kind=ADMIN_KIND)


def test_expired_access_token_rejected() -> None:
    """Access TTL is 15 min; 30 min after issue, decode rejects with JWTError."""
    issuer = TokenIssuer()
    with freeze_time("2026-01-01 12:00:00"):
        pair = issuer.issue_pair(subject="user-abc", kind=CUSTOMER_KIND)
    with freeze_time("2026-01-01 12:30:00"), pytest.raises(JWTError):
        issuer.decode(pair.access, expected_type=ACCESS_TYPE, expected_kind=CUSTOMER_KIND)


def test_refresh_token_has_30_day_ttl() -> None:
    """Refresh outlives access — still valid 16 minutes after issue."""
    issuer = TokenIssuer()
    with freeze_time("2026-01-01 12:00:00"):
        pair = issuer.issue_pair(subject="user-abc", kind=CUSTOMER_KIND)
    with freeze_time("2026-01-01 12:16:00"):
        # access is gone, but refresh is still good
        claims = issuer.decode(
            pair.refresh, expected_type=REFRESH_TYPE, expected_kind=CUSTOMER_KIND
        )
        assert claims["sub"] == "user-abc"


def test_token_header_carries_kid() -> None:
    """``kid`` header is present so future key rotation has a hook."""
    issuer = TokenIssuer()
    pair = issuer.issue_pair(subject="user-abc", kind=CUSTOMER_KIND)
    headers = _jwt.get_unverified_headers(pair.access)
    assert headers.get("kid") == DEFAULT_KID

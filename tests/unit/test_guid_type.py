"""GUID type — byte-swap round-trip and uuid7 properties."""

from __future__ import annotations

import time
import uuid

import pytest

from app.core.types import GUID, uuid7

# ─── GUID round-trip ──────────────────────────────────────────────────────────


def test_guid_round_trip_uuid_object() -> None:
    g = GUID()
    original = uuid.UUID("12345678-1234-5678-9abc-def012345678")
    encoded = g.process_bind_param(original, None)
    assert isinstance(encoded, bytes)
    assert len(encoded) == 16
    decoded = g.process_result_value(encoded, None)
    assert decoded == original


def test_guid_accepts_string_input() -> None:
    g = GUID()
    s = "12345678-1234-5678-9abc-def012345678"
    encoded = g.process_bind_param(s, None)
    assert isinstance(encoded, bytes)
    decoded = g.process_result_value(encoded, None)
    assert decoded == uuid.UUID(s)


def test_guid_byte_swap_matches_mysql_uuid_to_bin_layout() -> None:
    """Stored bytes follow MySQL ``UUID_TO_BIN(_, 1)`` — time-hi first.

    For input ``12345678-1234-5678-9abc-def012345678``:

    * time_low=12345678, time_mid=1234, time_hi_and_version=5678,
      clk=9abc, node=def012345678
    * After swap-1: time_hi-time_mid-time_low-clk-node
                  = 5678-1234-12345678-9abc-def012345678
    """
    g = GUID()
    original = uuid.UUID("12345678-1234-5678-9abc-def012345678")
    encoded = g.process_bind_param(original, None)
    expected = bytes.fromhex("567812341234567812345678".replace("12345678", "12345678"))
    # Build expected explicitly:
    expected = bytes.fromhex("5678" + "1234" + "12345678" + "9abc" + "def012345678")
    assert encoded == expected, f"got {encoded.hex()}, expected {expected.hex()}"


def test_guid_none_passes_through() -> None:
    g = GUID()
    assert g.process_bind_param(None, None) is None
    assert g.process_result_value(None, None) is None


def test_guid_rejects_non_uuid_input() -> None:
    g = GUID()
    with pytest.raises(TypeError):
        g.process_bind_param(12345, None)


def test_guid_round_trip_with_uuid7() -> None:
    """A freshly generated UUID7 round-trips identically."""
    g = GUID()
    original = uuid7()
    decoded = g.process_result_value(g.process_bind_param(original, None), None)
    assert decoded == original


# ─── uuid7 ────────────────────────────────────────────────────────────────────


def test_uuid7_version_is_7() -> None:
    assert uuid7().version == 7


def test_uuid7_variant_is_rfc4122() -> None:
    """Variant bits (62-63) must be 0b10 — RFC 4122."""
    assert uuid7().variant == uuid.RFC_4122


def test_uuid7_is_time_ordered() -> None:
    """Two uuid7s generated 2ms apart have monotonically increasing int values."""
    u1 = uuid7()
    time.sleep(0.002)
    u2 = uuid7()
    assert u2.int > u1.int


def test_uuid7_high_48_bits_match_unix_ms() -> None:
    """Top 48 bits of a uuid7 equal the unix-ms time at generation (within 1s)."""
    before_ms = int(time.time() * 1000)
    u = uuid7()
    after_ms = int(time.time() * 1000)
    encoded_ms = u.int >> 80
    assert before_ms - 1 <= encoded_ms <= after_ms + 1

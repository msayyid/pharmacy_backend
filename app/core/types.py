"""Custom SQLAlchemy types and UUID7 helper.

* :func:`uuid7` — RFC 9562 UUID v7 (48-bit ms timestamp + 4-bit version +
  12-bit rand_a + 2-bit variant + 62-bit rand_b). Implemented inline to
  avoid a new dep — see DECISION_LOG.
* :class:`GUID` — UUID stored as ``BINARY(16)`` with byte-swapped layout
  that mirrors MySQL's ``UUID_TO_BIN(uuid_str, 1)`` for B-tree locality.
  Without the swap, time-ordered UUIDs lose ordering on disk and B-tree
  inserts become random.

Reference: BACKEND_BLUEPRINT.md §6.2, §7.2.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from sqlalchemy.types import BINARY, TypeDecorator

# ─── UUID7 ─────────────────────────────────────────────────────────────────────


def uuid7() -> uuid.UUID:
    """Generate a UUID v7 — time-ordered, 128-bit, RFC 9562 compliant.

    Layout (big-endian):

    * bits 127..80 (48): unix milliseconds
    * bits 79..76  (4):  version (= 7)
    * bits 75..64  (12): rand_a
    * bits 63..62  (2):  variant (= 0b10)
    * bits 61..0   (62): rand_b
    """
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF  # 48 bits
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits
    rand_a = (rand >> 68) & 0xFFF  # top 12 of 80
    rand_b = rand & ((1 << 62) - 1)  # bottom 62 of 80

    uuid_int = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=uuid_int)


# ─── GUID column type ─────────────────────────────────────────────────────────


class GUID(TypeDecorator[uuid.UUID]):
    """UUID stored as ``BINARY(16)`` with byte-swapped layout for B-tree locality.

    Accepts ``uuid.UUID`` or 36-char string on bind. Returns ``uuid.UUID`` on
    fetch.

    The swap mirrors MySQL ``UUID_TO_BIN(uuid_str, 1)`` — for an input
    ``aabbccdd-eeff-gghh-iijj-kkllmmnnoopp`` the stored bytes are
    ``gghh eeff aabbccdd iijj kkllmmnnoopp`` (time-hi first). Time-ordered
    UUIDs (UUIDv1, UUIDv7) gain monotonic byte prefixes, so InnoDB B-tree
    pages stay densely packed.
    """

    impl = BINARY(16)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> bytes | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = uuid.UUID(value)
        if not isinstance(value, uuid.UUID):
            raise TypeError(f"GUID expected uuid.UUID or str, got {type(value).__name__}")
        b = value.bytes
        return b[6:8] + b[4:6] + b[0:4] + b[8:]

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        if value is None:
            return None
        b: bytes = value
        original = b[4:8] + b[2:4] + b[0:2] + b[8:]
        return uuid.UUID(bytes=original)

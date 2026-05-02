"""Security primitives.

Phase 1 stub. Phase 4 lands:

* ``hash_password`` / ``verify_password`` (argon2id + pepper)
* ``hash_otp`` / ``verify_otp`` (HMAC-SHA256 + pepper, constant-time)
* ``TokenIssuer`` (15-min JWT access + 30-day rotating refresh)
* ``normalise_phone`` (E.164 via ``phonenumbers`` library, KG region)

Reference: BACKEND_BLUEPRINT.md §14.6.
"""

from __future__ import annotations

# Intentionally empty in Phase 1.

"""Custom SQLAlchemy types.

Phase 2 lands the ``GUID`` type — ``BINARY(16)`` with byte-swapped layout to
match ``UUID_TO_BIN(_, 1)`` for B-tree locality on MySQL InnoDB.

Reference: BACKEND_BLUEPRINT.md §6.2 + §7.2; CLAUDE.md "Tech stack reality
checks > Database is MySQL 8".
"""

from __future__ import annotations

# Intentionally empty in Phase 1.

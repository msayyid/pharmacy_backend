"""Admin API — ``/api/admin/v1`` namespace.

Sub-routers land in Phase 5+: auth, products, inventory, orders, reports,
users, team, audit. Phase 1 leaves this empty.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/admin/v1")

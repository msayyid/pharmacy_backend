"""Customer API — ``/api/v1`` namespace.

Sub-routers land in Phase 4+: auth, account, catalog, search, cart, checkout,
orders, content. Phase 1 leaves this empty so the router is wired and
existing.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")

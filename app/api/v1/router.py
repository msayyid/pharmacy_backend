"""Customer API — ``/api/v1`` namespace.

Sub-routers:
* ``auth``, ``account`` (Phase 4)
* ``categories``, ``symptoms``, ``branches``, ``products``, ``search``
  (Phase 7 — storefront)

Phase 8+ adds cart, checkout, orders.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    account,
    auth,
    branches,
    categories,
    products,
    search,
    symptoms,
)

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(account.router)
router.include_router(categories.router)
router.include_router(symptoms.router)
router.include_router(branches.router)
router.include_router(products.router)
router.include_router(search.router)

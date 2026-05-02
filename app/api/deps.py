"""FastAPI dependencies (DI graph).

* Type aliases: ``SettingsDep``, ``LangDep``, ``RedisDep``, ``DbSession``.
* Repository factories: ``get_*_repository`` per aggregate.
* Service factories: ``get_otp_service``, ``get_auth_service``,
  ``get_account_service``, ``get_admin_auth_service``.
* Customer / admin auth deps live in
  :mod:`app.domain.identity.dependencies` to keep the domain self-contained.

Reference: BACKEND_BLUEPRINT.md §13.2.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import Cookie, Depends, Header
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.i18n import resolve_language
from app.core.redis import get_redis
from app.core.security import TokenIssuer
from app.domain.catalog.images import ProductImageService
from app.domain.catalog.import_csv import ProductImportService
from app.domain.catalog.products import ProductService
from app.domain.catalog.repositories import (
    ActiveIngredientRepository,
    CategoryRepository,
    ManufacturerRepository,
    ProductRepository,
    SymptomRepository,
)
from app.domain.catalog.search import SearchService
from app.domain.catalog.services import CatalogAdminService
from app.domain.catalog.storefront import StorefrontCatalogService
from app.domain.identity.models import User
from app.domain.identity.repositories import (
    AdminSessionRepository,
    AdminUserRepository,
    OtpRepository,
    UserAddressRepository,
    UserRepository,
)
from app.domain.identity.services import (
    AccountService,
    AdminAuthService,
    AuthService,
    OtpService,
)
from app.domain.inventory.repositories import (
    BranchProductRepository,
    BranchRepository,
    InventoryBatchRepository,
    StockMovementRepository,
    SupplierRepository,
)
from app.domain.inventory.services import InventoryService
from app.domain.ops.repositories import (
    AdminAuditLogRepository,
    SearchLogRepository,
)
from app.domain.ops.services import AdminAuditLogService
from app.domain.orders.cart_service import CartService
from app.domain.orders.checkout_service import CheckoutService
from app.domain.orders.order_service import OrderService
from app.domain.orders.repositories import (
    CartRepository,
    OrderRepository,
    OrderSequenceRepository,
    OrderStatusHistoryRepository,
)
from app.integrations.sms.base import get_sms_queue

# ─── Type aliases ─────────────────────────────────────────────────────────────

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]


def get_lang(
    accept_language: Annotated[str | None, Header()] = None,
) -> str:
    """Resolve the request language from ``Accept-Language``."""
    return resolve_language(accept_language)


LangDep = Annotated[str, Depends(get_lang)]


def get_redis_dep() -> Redis:
    """FastAPI dependency wrapping the module-level Redis client."""
    return get_redis()


RedisDep = Annotated[Redis, Depends(get_redis_dep)]


# ─── Storefront branch resolver ──────────────────────────────────────────────


def get_storefront_branch_id() -> int:
    """Default branch for storefront reads.

    MVP runs single-branch (Bishkek Central, ``branch_id=1``). Phase 2
    of the product roadmap adds a branch picker; this dep is the
    seam — change the body when the picker UX lands. Documented in
    DECISION_LOG.
    """
    return 1


BranchIdDep = Annotated[int, Depends(get_storefront_branch_id)]


# ─── Repository factories ────────────────────────────────────────────────────


def get_user_repository(session: DbSession) -> UserRepository:
    return UserRepository(session)


def get_user_address_repository(session: DbSession) -> UserAddressRepository:
    return UserAddressRepository(session)


def get_otp_repository(session: DbSession) -> OtpRepository:
    return OtpRepository(session)


def get_admin_user_repository(session: DbSession) -> AdminUserRepository:
    return AdminUserRepository(session)


def get_admin_session_repository(session: DbSession) -> AdminSessionRepository:
    return AdminSessionRepository(session)


def get_branch_repository(session: DbSession) -> BranchRepository:
    return BranchRepository(session)


def get_supplier_repository(session: DbSession) -> SupplierRepository:
    return SupplierRepository(session)


def get_branch_product_repository(session: DbSession) -> BranchProductRepository:
    return BranchProductRepository(session)


def get_inventory_batch_repository(session: DbSession) -> InventoryBatchRepository:
    return InventoryBatchRepository(session)


def get_stock_movement_repository(session: DbSession) -> StockMovementRepository:
    return StockMovementRepository(session)


def get_manufacturer_repository(session: DbSession) -> ManufacturerRepository:
    return ManufacturerRepository(session)


def get_active_ingredient_repository(
    session: DbSession,
) -> ActiveIngredientRepository:
    return ActiveIngredientRepository(session)


def get_category_repository(session: DbSession) -> CategoryRepository:
    return CategoryRepository(session)


def get_symptom_repository(session: DbSession) -> SymptomRepository:
    return SymptomRepository(session)


def get_product_repository(session: DbSession) -> ProductRepository:
    return ProductRepository(session)


def get_admin_audit_repository(session: DbSession) -> AdminAuditLogRepository:
    return AdminAuditLogRepository(session)


def get_admin_audit_service(
    repo: Annotated[AdminAuditLogRepository, Depends(get_admin_audit_repository)],
) -> AdminAuditLogService:
    return AdminAuditLogService(repo)


# ─── Service factories ───────────────────────────────────────────────────────


def get_token_issuer(settings: SettingsDep) -> TokenIssuer:
    return TokenIssuer(settings)


def get_otp_service(
    settings: SettingsDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    otps: Annotated[OtpRepository, Depends(get_otp_repository)],
    token_issuer: Annotated[TokenIssuer, Depends(get_token_issuer)],
) -> OtpService:
    return OtpService(
        settings=settings,
        users=users,
        otps=otps,
        sms_queue=get_sms_queue(),
        token_issuer=token_issuer,
    )


def get_auth_service(
    settings: SettingsDep,
    users: Annotated[UserRepository, Depends(get_user_repository)],
    token_issuer: Annotated[TokenIssuer, Depends(get_token_issuer)],
) -> AuthService:
    return AuthService(
        settings=settings,
        users=users,
        token_issuer=token_issuer,
    )


def get_account_service(
    users: Annotated[UserRepository, Depends(get_user_repository)],
    addresses: Annotated[UserAddressRepository, Depends(get_user_address_repository)],
) -> AccountService:
    return AccountService(users=users, addresses=addresses)


def get_admin_auth_service(
    settings: SettingsDep,
    admins: Annotated[AdminUserRepository, Depends(get_admin_user_repository)],
    sessions: Annotated[AdminSessionRepository, Depends(get_admin_session_repository)],
) -> AdminAuthService:
    return AdminAuthService(settings=settings, admins=admins, sessions=sessions)


def get_catalog_admin_service(
    manufacturers: Annotated[ManufacturerRepository, Depends(get_manufacturer_repository)],
    ingredients: Annotated[ActiveIngredientRepository, Depends(get_active_ingredient_repository)],
    categories: Annotated[CategoryRepository, Depends(get_category_repository)],
    symptoms: Annotated[SymptomRepository, Depends(get_symptom_repository)],
    audit: Annotated[AdminAuditLogService, Depends(get_admin_audit_service)],
) -> CatalogAdminService:
    return CatalogAdminService(
        manufacturers=manufacturers,
        ingredients=ingredients,
        categories=categories,
        symptoms=symptoms,
        audit=audit,
    )


def get_product_service(
    products: Annotated[ProductRepository, Depends(get_product_repository)],
    manufacturers: Annotated[ManufacturerRepository, Depends(get_manufacturer_repository)],
    categories: Annotated[CategoryRepository, Depends(get_category_repository)],
    ingredients: Annotated[ActiveIngredientRepository, Depends(get_active_ingredient_repository)],
    symptoms: Annotated[SymptomRepository, Depends(get_symptom_repository)],
    audit: Annotated[AdminAuditLogService, Depends(get_admin_audit_service)],
) -> ProductService:
    return ProductService(
        products=products,
        manufacturers=manufacturers,
        categories=categories,
        ingredients=ingredients,
        symptoms=symptoms,
        audit=audit,
    )


def get_product_image_service(
    settings: SettingsDep,
    products: Annotated[ProductRepository, Depends(get_product_repository)],
    audit: Annotated[AdminAuditLogService, Depends(get_admin_audit_service)],
) -> ProductImageService:
    return ProductImageService(
        products=products,
        audit=audit,
        storage_dir=Path(settings.image_storage_dir),
        public_base_url=settings.image_public_base_url,
        max_bytes=settings.image_max_bytes,
    )


def get_product_import_service(
    products: Annotated[ProductRepository, Depends(get_product_repository)],
    manufacturers: Annotated[ManufacturerRepository, Depends(get_manufacturer_repository)],
    categories: Annotated[CategoryRepository, Depends(get_category_repository)],
    ingredients: Annotated[ActiveIngredientRepository, Depends(get_active_ingredient_repository)],
    symptoms: Annotated[SymptomRepository, Depends(get_symptom_repository)],
    product_service: Annotated[ProductService, Depends(get_product_service)],
) -> ProductImportService:
    return ProductImportService(
        products=products,
        manufacturers=manufacturers,
        categories=categories,
        ingredients=ingredients,
        symptoms=symptoms,
        product_service=product_service,
    )


def get_inventory_service(
    session: DbSession,
    branches: Annotated[BranchRepository, Depends(get_branch_repository)],
    suppliers: Annotated[SupplierRepository, Depends(get_supplier_repository)],
    branch_products: Annotated[BranchProductRepository, Depends(get_branch_product_repository)],
    batches: Annotated[InventoryBatchRepository, Depends(get_inventory_batch_repository)],
    movements: Annotated[StockMovementRepository, Depends(get_stock_movement_repository)],
    audit: Annotated[AdminAuditLogService, Depends(get_admin_audit_service)],
) -> InventoryService:
    return InventoryService(
        session=session,
        branches=branches,
        suppliers=suppliers,
        branch_products=branch_products,
        batches=batches,
        movements=movements,
        audit=audit,
    )


def get_search_log_repository(session: DbSession) -> SearchLogRepository:
    return SearchLogRepository(session)


def get_storefront_catalog_service(
    categories: Annotated[CategoryRepository, Depends(get_category_repository)],
    products: Annotated[ProductRepository, Depends(get_product_repository)],
    symptoms: Annotated[SymptomRepository, Depends(get_symptom_repository)],
    branches: Annotated[BranchRepository, Depends(get_branch_repository)],
) -> StorefrontCatalogService:
    return StorefrontCatalogService(
        categories=categories,
        products=products,
        symptoms=symptoms,
        branches=branches,
    )


def get_search_service(
    products: Annotated[ProductRepository, Depends(get_product_repository)],
    categories: Annotated[CategoryRepository, Depends(get_category_repository)],
    symptoms: Annotated[SymptomRepository, Depends(get_symptom_repository)],
    search_log: Annotated[SearchLogRepository, Depends(get_search_log_repository)],
) -> SearchService:
    return SearchService(
        products=products,
        categories=categories,
        symptoms=symptoms,
        search_log=search_log,
    )


# ─── Phase 8 — Order / cart factories ────────────────────────────────────────


def get_cart_repository(session: DbSession) -> CartRepository:
    return CartRepository(session)


def get_order_repository(session: DbSession) -> OrderRepository:
    return OrderRepository(session)


def get_order_history_repository(
    session: DbSession,
) -> OrderStatusHistoryRepository:
    return OrderStatusHistoryRepository(session)


def get_order_sequence_repository(session: DbSession) -> OrderSequenceRepository:
    return OrderSequenceRepository(session)


def get_cart_service(
    carts: Annotated[CartRepository, Depends(get_cart_repository)],
    products: Annotated[ProductRepository, Depends(get_product_repository)],
    branch_products: Annotated[BranchProductRepository, Depends(get_branch_product_repository)],
) -> CartService:
    return CartService(
        carts=carts,
        products=products,
        branch_products=branch_products,
    )


def get_checkout_service(
    carts: Annotated[CartRepository, Depends(get_cart_repository)],
    orders: Annotated[OrderRepository, Depends(get_order_repository)],
    order_history: Annotated[OrderStatusHistoryRepository, Depends(get_order_history_repository)],
    order_sequence: Annotated[OrderSequenceRepository, Depends(get_order_sequence_repository)],
    products: Annotated[ProductRepository, Depends(get_product_repository)],
    branch_products: Annotated[BranchProductRepository, Depends(get_branch_product_repository)],
    batches: Annotated[InventoryBatchRepository, Depends(get_inventory_batch_repository)],
    addresses: Annotated[UserAddressRepository, Depends(get_user_address_repository)],
    inventory: Annotated[InventoryService, Depends(get_inventory_service)],
) -> CheckoutService:
    return CheckoutService(
        carts=carts,
        orders=orders,
        order_history=order_history,
        order_sequence=order_sequence,
        products=products,
        branch_products=branch_products,
        batches=batches,
        addresses=addresses,
        inventory=inventory,
    )


def get_customer_order_service(
    orders: Annotated[OrderRepository, Depends(get_order_repository)],
    order_history: Annotated[OrderStatusHistoryRepository, Depends(get_order_history_repository)],
    cart_service: Annotated[CartService, Depends(get_cart_service)],
    products: Annotated[ProductRepository, Depends(get_product_repository)],
    branch_products: Annotated[BranchProductRepository, Depends(get_branch_product_repository)],
    inventory: Annotated[InventoryService, Depends(get_inventory_service)],
) -> OrderService:
    return OrderService(
        orders=orders,
        order_history=order_history,
        cart_service=cart_service,
        products=products,
        branch_products=branch_products,
        inventory=inventory,
    )


# ─── Cart owner resolver (user OR guest cookie) ──────────────────────────────


GUEST_CART_COOKIE = "pharmacy_cart_session"
GUEST_CART_COOKIE_TTL = 30 * 24 * 60 * 60  # 30 days, seconds


# Lazy import here so :mod:`app.domain.identity.dependencies` (which
# imports ``SettingsDep`` from this module) can finish loading before
# we reference its symbols. Eager top-level import would deadlock
# Python's module-loading machinery.
def _optional_current_user_dep() -> Any:
    from app.domain.identity.dependencies import get_optional_current_user

    return get_optional_current_user


async def get_cart_owner(
    user: Annotated[User | None, Depends(_optional_current_user_dep())],
    pharmacy_cart_session: Annotated[str | None, Cookie()] = None,
) -> tuple[User | None, str | None]:
    """Return ``(user_or_none, session_id_or_none)`` for cart routes.

    Logged-in users always win — their cart is keyed by user_id even
    if the cookie is also present (the cookie was used pre-login; the
    merge happens at login-time, not on every request).
    """
    return (user, pharmacy_cart_session if user is None else None)


CartOwner = Annotated[tuple[User | None, str | None], Depends(get_cart_owner)]

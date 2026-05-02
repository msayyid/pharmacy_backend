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
from typing import Annotated

from fastapi import Depends, Header
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
from app.domain.catalog.services import CatalogAdminService
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
from app.domain.ops.repositories import AdminAuditLogRepository
from app.domain.ops.services import AdminAuditLogService
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

"""Catalog admin service unit-ish tests — exercise rules with a real session.

These hit the real DB but stay focused on service-layer business rules
(uniqueness, soft-delete, has-children, replace-translations semantics)
rather than HTTP/auth concerns.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.domain.catalog.repositories import (
    ActiveIngredientRepository,
    CategoryRepository,
    ManufacturerRepository,
    SymptomRepository,
)
from app.domain.catalog.schemas import (
    ActiveIngredientCreate,
    ActiveIngredientTranslationIn,
    ActiveIngredientUpdate,
    CategoryCreate,
    CategoryTranslationIn,
    ManufacturerCreate,
    ManufacturerUpdate,
    SymptomCreate,
    SymptomTranslationIn,
)
from app.domain.catalog.services import CatalogAdminService
from app.domain.identity.models import AdminUser
from app.domain.ops.repositories import AdminAuditLogRepository
from app.domain.ops.services import AdminAuditLogService
from tests.factories.catalog import (
    seed_category,
    seed_manufacturer,
    seed_product,
)

pytestmark = pytest.mark.unit


def _make_service(session: AsyncSession) -> CatalogAdminService:
    return CatalogAdminService(
        manufacturers=ManufacturerRepository(session),
        ingredients=ActiveIngredientRepository(session),
        categories=CategoryRepository(session),
        symptoms=SymptomRepository(session),
        audit=AdminAuditLogService(AdminAuditLogRepository(session)),
    )


async def _make_actor(session: AsyncSession, *, suffix: str) -> AdminUser:
    """Persist a dummy admin so audit ``admin_user_id`` FK passes."""
    admin = AdminUser(
        email=f"actor-{suffix}@pharmacy.kg",
        password_hash="x" * 60,
        first_name="Actor",
        last_name="User",
        role="super_admin",
        is_active=True,
    )
    session.add(admin)
    await session.flush()
    return admin


# ─── Manufacturers ────────────────────────────────────────────────────────────


async def test_create_manufacturer_persists_and_audits(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="mfr-create")

    m = await svc.create_manufacturer(
        payload=ManufacturerCreate(name="Roche", country_code="CH"),
        actor=actor,
    )
    assert m.id is not None
    assert m.name == "Roche"


async def test_create_manufacturer_duplicate_name_raises_conflict(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="mfr-dup")
    await seed_manufacturer(session, name="Pfizer")

    with pytest.raises(ConflictError) as ei:
        await svc.create_manufacturer(
            payload=ManufacturerCreate(name="Pfizer"),
            actor=actor,
        )
    assert ei.value.context["code"] == "manufacturer_name_exists"


async def test_update_manufacturer_not_found_raises(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="mfr-404")
    with pytest.raises(NotFoundError):
        await svc.update_manufacturer(
            999_999,
            payload=ManufacturerUpdate(name="X"),
            actor=actor,
        )


async def test_delete_manufacturer_with_active_products_raises(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="mfr-active")
    mfr = await seed_manufacturer(session, name="HasOne")
    cat = await seed_category(session, slug="cat-mfr-del")
    await seed_product(
        session,
        sku="MFR-DEL-1",
        slug="mfr-del-1",
        category_id=cat.id,
        manufacturer_id=mfr.id,
    )

    with pytest.raises(ConflictError) as ei:
        await svc.delete_manufacturer(mfr.id, actor=actor)
    assert ei.value.context["code"] == "manufacturer_has_products"


# ─── Active ingredients ───────────────────────────────────────────────────────


async def test_update_ingredient_replaces_translations(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="ai-replace")
    repo = ActiveIngredientRepository(session)

    ai = await svc.create_ingredient(
        payload=ActiveIngredientCreate(
            inn_name="metformin",
            translations=[
                ActiveIngredientTranslationIn(language_code="ru", name="Метформин"),
                ActiveIngredientTranslationIn(language_code="en", name="Metformin"),
            ],
        ),
        actor=actor,
    )
    # Re-fetch with translations eager-loaded — the model uses lazy="raise".
    reloaded = await repo.get_by_id_with_translations(ai.id)
    assert reloaded is not None
    assert {t.language_code for t in reloaded.translations} == {"ru", "en"}

    await svc.update_ingredient(
        ai.id,
        payload=ActiveIngredientUpdate(
            translations=[
                ActiveIngredientTranslationIn(language_code="ky", name="Метформин"),
            ]
        ),
        actor=actor,
    )
    after = await repo.get_by_id_with_translations(ai.id)
    assert after is not None
    assert {t.language_code for t in after.translations} == {"ky"}


# ─── Categories ───────────────────────────────────────────────────────────────


async def test_create_category_auto_slugifies_from_translation(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="cat-slug")
    c = await svc.create_category(
        payload=CategoryCreate(
            translations=[CategoryTranslationIn(language_code="ru", name="Сердечные средства")]
        ),
        actor=actor,
    )
    assert c.slug == "serdechnye-sredstva"


async def test_create_category_without_slug_or_translation_raises(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="cat-noslug")
    with pytest.raises(ValidationError) as ei:
        await svc.create_category(
            payload=CategoryCreate(translations=[]),
            actor=actor,
        )
    assert ei.value.context["code"] == "slug_required_or_translation_required"


async def test_delete_category_with_children_raises(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="cat-kids")
    parent = await seed_category(session, slug="cat-parent-del")
    await seed_category(session, slug="cat-child-del", parent_id=parent.id)
    with pytest.raises(ConflictError) as ei:
        await svc.delete_category(parent.id, actor=actor)
    assert ei.value.context["code"] == "category_has_children"


# ─── Symptoms ─────────────────────────────────────────────────────────────────


async def test_create_symptom_unique_slug_increments(
    session: AsyncSession,
) -> None:
    svc = _make_service(session)
    actor = await _make_actor(session, suffix="sym-uniq")

    s1 = await svc.create_symptom(
        payload=SymptomCreate(
            translations=[SymptomTranslationIn(language_code="ru", name="Головная боль")]
        ),
        actor=actor,
    )
    assert s1.slug == "golovnaia-bol"

    s2 = await svc.create_symptom(
        payload=SymptomCreate(
            translations=[SymptomTranslationIn(language_code="ru", name="Головная боль")]
        ),
        actor=actor,
    )
    assert s2.slug == "golovnaia-bol-2"

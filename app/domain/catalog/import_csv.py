"""Product bulk-import service — CSV per the locked column contract.

Phase 5 ships CSV only (≤ 500 rows synchronous); XLSX deferred. The
column contract is locked in ``BUILD_PROGRESS.md`` and reproduced
verbatim below — changes require a phase-boundary decision.

Two operations:

* :meth:`dry_run` — parse + validate references; return a structured
  summary without mutating state.
* :meth:`apply`   — parse + upsert per row by SKU.

Idempotency: SKUs are matched. Existing → update (translations + M:N
replaced). New → insert. Missing-from-file SKUs are NEVER deleted.

Reference: F-ADM-CAT-002 (PRODUCT §8.5); CLAUDE_CODE_PROMPTS Phase 5.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from app.core.errors import ValidationError
from app.domain.catalog.models import Category
from app.domain.catalog.products import ProductService
from app.domain.catalog.repositories import (
    ActiveIngredientRepository,
    CategoryRepository,
    ManufacturerRepository,
    ProductRepository,
    SymptomRepository,
)
from app.domain.catalog.schemas import (
    BulkImportRowError,
    BulkImportSummary,
    ProductCreate,
)
from app.domain.identity.models import AdminUser

_VALID_FORMS: frozenset[str] = frozenset(
    {
        "tablet",
        "capsule",
        "syrup",
        "drops",
        "cream",
        "ointment",
        "gel",
        "spray",
        "inhaler",
        "injection",
        "suppository",
        "patch",
        "powder",
        "solution",
        "suspension",
        "lozenge",
        "other",
    }
)
_VALID_DOSAGE_UNITS: frozenset[str] = frozenset({"mg", "g", "mcg", "ml", "IU", "%"})

_TRUE_TOKENS: frozenset[str] = frozenset({"true", "1", "yes", "y", "t"})
_FALSE_TOKENS: frozenset[str] = frozenset({"false", "0", "no", "n", "f", ""})

DEFAULT_MAX_ROWS = 500


def _parse_bool(s: str, default: bool) -> bool | None:
    """Returns the boolean value, or None if unparseable."""
    v = s.strip().lower()
    if v in _TRUE_TOKENS:
        return True
    if v in _FALSE_TOKENS:
        return default if v == "" else False
    return None


def _stripped(s: str | None) -> str | None:
    if s is None:
        return None
    out = s.strip()
    return out if out else None


def _opt_int(s: str | None) -> int | None:
    v = _stripped(s)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError as e:
        raise ValueError(f"invalid integer: {v!r}") from e


def _opt_decimal(s: str | None) -> Decimal | None:
    v = _stripped(s)
    if v is None:
        return None
    try:
        return Decimal(v)
    except InvalidOperation as e:
        raise ValueError(f"invalid decimal: {v!r}") from e


class TooManyRowsError(ValidationError):
    code = "import_too_many_rows"


class ProductImportService:
    def __init__(
        self,
        *,
        products: ProductRepository,
        manufacturers: ManufacturerRepository,
        categories: CategoryRepository,
        ingredients: ActiveIngredientRepository,
        symptoms: SymptomRepository,
        product_service: ProductService,
        max_rows: int = DEFAULT_MAX_ROWS,
    ) -> None:
        self.products = products
        self.manufacturers = manufacturers
        self.categories = categories
        self.ingredients = ingredients
        self.symptoms = symptoms
        self.product_service = product_service
        self.max_rows = max_rows

    # ─── Public API ─────────────────────────────────────────────────────────

    async def dry_run(self, csv_bytes: bytes) -> BulkImportSummary:
        rows, errors = await self._parse(csv_bytes)
        n_create = 0
        n_update = 0
        for row in rows:
            existing = await self.products.get_by_sku(row["sku"])
            if existing is None:
                n_create += 1
            else:
                n_update += 1
        return BulkImportSummary(
            n_rows=len(rows) + len(errors),
            n_create=n_create,
            n_update=n_update,
            n_skip=len(errors),
            errors=errors,
        )

    async def apply(
        self,
        csv_bytes: bytes,
        *,
        actor: AdminUser,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> BulkImportSummary:
        rows, errors = await self._parse(csv_bytes)
        if errors:
            return BulkImportSummary(
                n_rows=len(rows) + len(errors),
                n_create=0,
                n_update=0,
                n_skip=len(rows) + len(errors),
                errors=errors,
            )

        n_create = 0
        n_update = 0
        for row in rows:
            payload = self._row_to_create(row)
            _, created = await self.product_service.upsert_from_import(
                sku=row["sku"],
                payload=payload,
                actor=actor,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            if created:
                n_create += 1
            else:
                n_update += 1

        return BulkImportSummary(
            n_rows=len(rows),
            n_create=n_create,
            n_update=n_update,
            n_skip=0,
            errors=[],
        )

    # ─── Parsing ────────────────────────────────────────────────────────────

    async def _parse(
        self, csv_bytes: bytes
    ) -> tuple[list[dict[str, Any]], list[BulkImportRowError]]:
        try:
            text = csv_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            return ([], [BulkImportRowError(row=0, message=f"utf-8 decode failed: {e}")])

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or "sku" not in reader.fieldnames:
            return (
                [],
                [BulkImportRowError(row=0, message="missing required column: sku")],
            )

        rows: list[dict[str, Any]] = []
        errors: list[BulkImportRowError] = []
        seen_skus: set[str] = set()

        for row_idx, raw in enumerate(reader, start=1):
            if row_idx > self.max_rows:
                raise TooManyRowsError(code="import_too_many_rows", max_rows=self.max_rows)
            parsed, row_errors = await self._parse_row(row_idx, raw, seen_skus)
            if row_errors:
                errors.extend(row_errors)
                continue
            assert parsed is not None
            rows.append(parsed)
            seen_skus.add(parsed["sku"])

        return (rows, errors)

    async def _parse_row(  # noqa: PLR0911, PLR0912, PLR0915 — single-pass row validator
        self,
        row_idx: int,
        raw: dict[str, Any],
        seen_skus: set[str],
    ) -> tuple[dict[str, Any] | None, list[BulkImportRowError]]:
        errors: list[BulkImportRowError] = []
        sku = (raw.get("sku") or "").strip()
        if not sku:
            errors.append(BulkImportRowError(row=row_idx, message="missing sku"))
            return (None, errors)
        if sku in seen_skus:
            errors.append(
                BulkImportRowError(row=row_idx, sku=sku, message="duplicate sku within file")
            )
            return (None, errors)

        # Required: category_path
        category_path = (raw.get("category_path") or "").strip()
        if not category_path:
            errors.append(
                BulkImportRowError(
                    row=row_idx,
                    sku=sku,
                    field="category_path",
                    message="required",
                )
            )
            return (None, errors)
        cat = await self._resolve_category(category_path)
        if cat is None:
            errors.append(
                BulkImportRowError(
                    row=row_idx,
                    sku=sku,
                    field="category_path",
                    message=f"category not found: {category_path}",
                )
            )
            return (None, errors)

        form = (raw.get("form") or "other").strip().lower()
        if form not in _VALID_FORMS:
            errors.append(
                BulkImportRowError(
                    row=row_idx,
                    sku=sku,
                    field="form",
                    message=f"invalid form: {form}",
                )
            )
            return (None, errors)

        # Manufacturer (optional, by name)
        manufacturer_id: int | None = None
        mfr_name = (raw.get("manufacturer") or "").strip()
        if mfr_name:
            mfr = await self.manufacturers.get_by_name(mfr_name)
            if mfr is None:
                errors.append(
                    BulkImportRowError(
                        row=row_idx,
                        sku=sku,
                        field="manufacturer",
                        message=f"manufacturer not found: {mfr_name}",
                    )
                )
                return (None, errors)
            manufacturer_id = mfr.id

        # Booleans
        try:
            requires_prescription = _parse_bool(
                raw.get("requires_prescription") or "", default=False
            )
            requires_cold_chain = _parse_bool(raw.get("requires_cold_chain") or "", default=False)
            is_active = _parse_bool(raw.get("is_active") or "", default=True)
            is_featured = _parse_bool(raw.get("is_featured") or "", default=False)
        except ValueError as e:  # pragma: no cover — _parse_bool returns None on bad input
            errors.append(BulkImportRowError(row=row_idx, sku=sku, message=f"bool parse: {e}"))
            return (None, errors)
        for fname, val in (
            ("requires_prescription", requires_prescription),
            ("requires_cold_chain", requires_cold_chain),
            ("is_active", is_active),
            ("is_featured", is_featured),
        ):
            if val is None:
                errors.append(
                    BulkImportRowError(
                        row=row_idx,
                        sku=sku,
                        field=fname,
                        message=f"unrecognised boolean: {raw.get(fname)!r}",
                    )
                )
                return (None, errors)

        # Numerics
        try:
            min_age = _opt_int(raw.get("min_age"))
            max_per_order = _opt_int(raw.get("max_per_order"))
            weight_grams = _opt_int(raw.get("weight_grams"))
            storage_temp_min_c = _opt_int(raw.get("storage_temp_min_c"))
            storage_temp_max_c = _opt_int(raw.get("storage_temp_max_c"))
            pack_quantity = _opt_decimal(raw.get("pack_quantity"))
        except ValueError as e:
            errors.append(BulkImportRowError(row=row_idx, sku=sku, message=str(e)))
            return (None, errors)

        # Active ingredients: "Paracetamol:500:mg;Caffeine:50:mg"
        active_ingredients: list[dict[str, Any]] = []
        ai_str = (raw.get("active_ingredients") or "").strip()
        if ai_str:
            for triple_idx, triple_raw in enumerate(ai_str.split(";")):
                triple = triple_raw.strip()
                if not triple:
                    continue
                parts = triple.split(":")
                if len(parts) != 3:  # noqa: PLR2004 — Name:DOSE:UNIT triple
                    errors.append(
                        BulkImportRowError(
                            row=row_idx,
                            sku=sku,
                            field=f"active_ingredients[{triple_idx}]",
                            message="expected NAME:DOSE:UNIT",
                        )
                    )
                    return (None, errors)
                inn_name, dose_str, unit = (
                    parts[0].strip(),
                    parts[1].strip(),
                    parts[2].strip(),
                )
                ai = await self.ingredients.get_by_inn(inn_name)
                if ai is None:
                    errors.append(
                        BulkImportRowError(
                            row=row_idx,
                            sku=sku,
                            field=f"active_ingredients[{triple_idx}]",
                            message=f"ingredient not found: {inn_name}",
                        )
                    )
                    return (None, errors)
                try:
                    dose = Decimal(dose_str)
                except InvalidOperation:
                    errors.append(
                        BulkImportRowError(
                            row=row_idx,
                            sku=sku,
                            field=f"active_ingredients[{triple_idx}]",
                            message=f"invalid dose: {dose_str!r}",
                        )
                    )
                    return (None, errors)
                if unit not in _VALID_DOSAGE_UNITS:
                    errors.append(
                        BulkImportRowError(
                            row=row_idx,
                            sku=sku,
                            field=f"active_ingredients[{triple_idx}]",
                            message=f"invalid dosage unit: {unit!r}",
                        )
                    )
                    return (None, errors)
                active_ingredients.append(
                    {
                        "active_ingredient_id": ai.id,
                        "dosage_amount": dose,
                        "dosage_unit": unit,
                    }
                )

        # Symptoms: semicolon-separated slugs
        symptom_ids: list[int] = []
        sym_str = (raw.get("symptoms") or "").strip()
        if sym_str:
            for sym_idx, slug_raw in enumerate(sym_str.split(";")):
                slug = slug_raw.strip()
                if not slug:
                    continue
                sym = await self.symptoms.get_by_slug(slug)
                if sym is None:
                    errors.append(
                        BulkImportRowError(
                            row=row_idx,
                            sku=sku,
                            field=f"symptoms[{sym_idx}]",
                            message=f"symptom slug not found: {slug}",
                        )
                    )
                    return (None, errors)
                symptom_ids.append(sym.id)

        # Translations
        translations: list[dict[str, Any]] = []
        for lang in ("ru", "ky", "en"):
            name = (raw.get(f"name_{lang}") or "").strip()
            if not name:
                continue
            translations.append(
                {
                    "language_code": lang,
                    "name": name,
                    "short_description": _stripped(raw.get(f"short_description_{lang}")),
                    "description": _stripped(raw.get(f"description_{lang}")),
                }
            )

        return (
            {
                "sku": sku,
                "barcode": _stripped(raw.get("barcode")),
                "slug": _stripped(raw.get("slug")),
                "manufacturer_id": manufacturer_id,
                "category_id": cat.id,
                "form": form,
                "pack_size_label": _stripped(raw.get("pack_size_label")),
                "pack_quantity": pack_quantity,
                "pack_unit": _stripped(raw.get("pack_unit")),
                "requires_prescription": requires_prescription,
                "min_age": min_age,
                "max_per_order": max_per_order,
                "weight_grams": weight_grams,
                "requires_cold_chain": requires_cold_chain,
                "storage_temp_min_c": storage_temp_min_c,
                "storage_temp_max_c": storage_temp_max_c,
                "is_active": is_active,
                "is_featured": is_featured,
                "translations": translations,
                "active_ingredients": active_ingredients,
                "symptom_ids": symptom_ids,
            },
            [],
        )

    async def _resolve_category(self, path: str) -> Category | None:
        """Walk a slash-delimited slug path: ``"analgesics/paracetamol"``."""
        parts = [p for p in path.strip().split("/") if p]
        if not parts:
            return None
        parent_id: int | None = None
        current: Category | None = None
        for slug in parts:
            stmt = select(Category).where(
                Category.slug == slug,
                Category.deleted_at.is_(None),
            )
            if parent_id is None:
                stmt = stmt.where(Category.parent_id.is_(None))
            else:
                stmt = stmt.where(Category.parent_id == parent_id)
            current = (await self.categories.session.execute(stmt)).scalar_one_or_none()
            if current is None:
                return None
            parent_id = current.id
        return current

    @staticmethod
    def _row_to_create(row: dict[str, Any]) -> ProductCreate:
        """Convert a parsed row into a ``ProductCreate`` payload."""
        return ProductCreate.model_validate(row)

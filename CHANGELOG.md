# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### Phase 0 (2026-05-02)
- Project initialised; specs and master plan in place.
- `BUILD_PLAN.md`, `BUILD_PROGRESS.md`, `OPEN_QUESTIONS.md` (12 substantive items), `RISKS.md` (top-10 ranked + watching list), `DECISION_LOG.md` template, this file.

#### Phase 8 — Cart, Checkout & Place-Order (2026-05-02) — complete

- **5 new tables** in `app/domain/orders/models.py`: `carts` (UUID PK + `chk_carts_owner` user_id-OR-session_id + 30-day expiry), `cart_items` (`UNIQUE(cart_id, product_id)` + `quantity > 0` + `price_snapshot >= 0`), `orders` (UUID PK, `order_number` UNIQUE, `chk_orders_total` enforces `total = subtotal + delivery_fee - discount_amount` via `op.execute`), `order_items` (one **per allocation** — `chk_order_items_total CHECK line_total = unit_price * quantity` via `op.execute`; `product_id` ON DELETE SET NULL preserves snapshot), `order_status_history` (append-only state-transition audit), and `order_sequences(year PK, last_assigned)` for atomic per-year `order_number` allocation. `StrEnum`s for `OrderStatus` / `PaymentStatus` / `PaymentMethod` / `DeliveryMethod`.
- **Migration `ff2951f68321 — create orders + cart`** lifts the deferred `fk_sm_order` foreign key on `stock_movements.order_id → orders.id` (Phase 6 left the column without a constraint because the table didn't exist). Hand-edited from autogen; `op.execute` for the multi-clause CHECKs. Round-trips clean.
- **Repositories** in `app/domain/orders/repositories.py`: `CartRepository` (get-or-create per user / per session, fetch with items, clear, prune-expired), `OrderRepository` (get-by-id / get-by-number with eager items + history, paginated user listing), `OrderStatusHistoryRepository` (append), `OrderSequenceRepository` (`SELECT … FOR UPDATE` increment, formats `PH-YYYY-NNNNNN`).
- **`CartService`** (`app/domain/orders/cart_service.py`):
    - `get_or_create(user, session_id)` — guest-or-user resolution; creates with `branch_id` from the storefront resolver.
    - `add_item / update_qty / remove_item / clear` — re-validates stock + price, snapshots the price at write time, caps at `Product.max_per_order`.
    - `merge_guest_into_user` — additive on overlap (capped at `max_per_order`); deletes the guest cart afterwards.
    - `expire_check` raises `CartExpiredError` (HTTP 410) past `expires_at`.
- **`CheckoutService`** (`app/domain/orders/checkout_service.py`):
    - `quote(cart, delivery_method, payment_method)` — recomputes subtotal at current `branch_products.price`; computes delivery_fee per PRODUCT §11.4 (200 KGS / free over 1500 KGS / 0 for pickup); surfaces `stock_conflicts` + `price_conflicts` + `cold_chain_warning`. Does NOT reserve.
    - `place_order(...)` — the heart of the system. One transaction: idempotency check → re-validate stock + prices under `FOR UPDATE` → run `inventory.allocate_for_order` (FEFO with `FOR UPDATE SKIP LOCKED`) per cart line → allocate `order_number` via `OrderSequenceRepository` → insert `Order` → insert one `OrderItem` per allocation (cart line spanning two batches → two order_items) → `inventory.reserve` → `OrderStatusHistory(NULL → pending)` → card-payment scaffold (`payment_redirect_url` stub) → clear cart → idempotency store. ~250 lines, heavily commented.
- **Customer-side `OrderService`** (`app/domain/orders/order_service.py`):
    - `list_for_user` (paginated), `get_for_user` (404/403), `get_status_for_user` (slim polling shape).
    - `cancel_by_customer` — only `pending` / `confirmed`; releases reservations via Phase 6 `release_reservations`.
    - `reorder` — adds prior items to current cart with annotations (`added` / `out_of_stock` / `price_changed` / `product_deleted` / `max_per_order_capped`).
- **3 customer route modules** under `/api/v1`:
    - `cart.py` — `GET /cart`, `POST /cart/items`, `PATCH /cart/items/{id}`, `DELETE /cart/items/{id}`, `POST /cart/clear`. Guest cart cookie `pharmacy_cart_session` (HttpOnly, SameSite=Lax, 30-day TTL).
    - `checkout.py` — `POST /checkout/quote`, `POST /checkout/place` (`Idempotency-Key` REQUIRED — 400 if missing).
    - `me_orders.py` — `GET /me/orders`, `GET /me/orders/{n}`, `GET /me/orders/{n}/status`, `POST /me/orders/{n}/cancel`, `POST /me/orders/{n}/reorder`.
- **DI** — `get_cart_repository`, `get_order_repository`, `get_order_history_repository`, `get_order_sequence_repository`, `get_cart_service`, `get_checkout_service`, `get_customer_order_service`. Plus `CartOwner` dep that resolves `(user_or_None, session_id_or_None)` from the `OptionalCurrentUser` + `pharmacy_cart_session` cookie.
- **`OptionalCurrentUser`** dep (Phase 7 addition, used here) — same as `get_current_user` but returns `None` instead of raising on missing tokens.
- **57 new tests (396 total)**:
    - Unit: `test_cart_service.py` (8 — add caps at `max_per_order`; insufficient-stock rejects; update / remove; merge additive; merge promotes guest when no user cart; expired cart blocks adds); `test_checkout_service.py` (8 — delivery-fee math; quote totals + price-conflict surfacing; place_order happy path; place_order raises `CheckoutValidationError` on price drift; place_order idempotency replay returns cached); `test_order_service.py` (6 — cancel pending succeeds; cancel preparing blocked; cross-user 403; reorder adds in-stock; reorder flags `out_of_stock`; reorder flags `product_deleted`).
    - Integration: `test_order_concurrency.py` — parameterised `ORDER_CONCURRENT_LOOPS=30` × `test_two_orders_two_batches_partial_allocation` (two users, gather, both succeed without oversell, total reserved == 16); `test_idempotent_double_place_same_body_returns_cached`; `test_idempotent_conflict_on_different_body`. **Defaults to 30 loops; nightly CI bumps to 50** (DECISION_LOG'd).
    - E2E: `test_checkout_flow.py` (3 — guest cart → OTP login → place order → list orders → cancel; `Idempotency-Key required` 400; idempotent replay returns same order_number over HTTP).
- **Test factories**: `seed_minimal_order` (Phase 6 inventory tests now satisfy the `fk_sm_order` FK via this stub), `seed_cart`, `seed_cart_item`, `seed_cart_committed`.
- 396 tests pass; mypy --strict + ruff clean across 90 source files.

#### Phase 7 — Customer Discovery (2026-05-02) — complete

- **`SearchLog` model** + migration + ``SearchLogRepository`` (`append`, `popular_queries`, `recent_zero_results`). Stored in ``app/domain/ops/``.
- **`app/i18n/synonyms_ru.json`** — starter dictionary (~20 entries) covering PRODUCT §12.4: brand→INN (`панадол → парацетамол`, `анальгин → метамизол`, `цитрамон → парацетамол кофеин ацетилсалициловая кислота`); indication→symptom (`от головы → головная боль обезболивающее`, `жаропонижающее → температура …`); cold-family cluster; Latin↔Cyrillic.
- **Storefront repository methods** in `app/domain/catalog/repositories.py`:
    - `CategoryRepository.list_active_tree`, `SymptomRepository.list_active_with_translations`.
    - `ProductRepository.list_for_category` (single-query JOIN on translation + branch_products + primary image; `in_stock_only` filter; sort = `relevance | price_asc | price_desc | name | newest`).
    - `ProductRepository.list_for_symptom` — JOIN through `product_symptoms`.
    - `ProductRepository.get_storefront_detail` — full eager-loaded view (translations, images, ingredients with ingredient translations, symptoms with symptom translations, manufacturer, category with category translations).
    - `ProductRepository.list_substitutes` — same primary AI + dose, in stock, ≤ 4, ordered by price asc; falls back to same AI any-dose.
    - `ProductRepository.storefront_search` — composite-ranked SQL via `text()`: `exact_name = 1000 + name_prefix = 500 + FULLTEXT MATCH × 10 + ingredient/symptom/manufacturer EXISTS bonuses`; `HAVING score > 0`; ORDER BY `score DESC, is_featured DESC, created_at DESC`.
    - `ProductRepository.suggest` — prefix-match autocomplete.
    - Helpers `_guid_bind` / `_guid_load` to handle `BINARY(16)` byte-swap on raw `text()` parameters and result rows (the GUID `TypeDecorator` only runs on ORM/Core column ops).
- **Storefront schemas** (`app/domain/catalog/storefront_schemas.py`) — `CategoryNode`, `CategoryDetail`, `BreadcrumbItem`, `StorefrontProductCard`, `StorefrontProductDetail` (with localised name/description/usage/side-effects/contraindications/composition + manufacturer + category + ingredients + symptoms + images), `StorefrontSymptom`, `StorefrontBranch`, `SuggestResponse`, `SearchResultPage`, `StorefrontProductsPage`.
- **`StorefrontCatalogService`** (`app/domain/catalog/storefront.py`) — `get_categories_tree` (cached `v1:cat:tree:<lang>` 1h), `get_category_with_products`, `get_symptom_with_products`, `get_product_detail` (cached `v1:product:read:<slug>:<lang>` 5m, dumped via `model_dump(mode="json")` for orjson compatibility), `list_substitutes`, `list_active_branches`, `list_active_symptoms`. Translation fallback `lang → ru → first` per PRODUCT §13.1.
- **`SearchService`** (`app/domain/catalog/search.py`) — `search` (synonym expansion + ngram-friendly boolean MATCH + `search_log` append + popular_searches on zero-result), `suggest` (cached `v1:search:suggest:<lang>:<q>` 60s). Dictionary loaded once at module import.
- **Cache invalidation hooks**:
    - `CatalogAdminService.create_category / update_category / delete_category` → `invalidate("v1:cat:tree:")`.
    - `ProductService.update_product / soft_delete_product` → `invalidate(f"v1:product:read:{slug}:")`. Slug-rename case handled by invalidating both old and new slug.
    - `InventoryService.update_branch_product` → `invalidate(f"v1:product:read:{slug}:")`. Slug looked up via direct `select(Product.slug)` to avoid a cross-domain repo dep.
    - `cache.invalidate` is best-effort: silently no-ops when Redis is uninitialised so unit tests without Redis don't break write paths.
- **5 customer route modules** under `/api/v1`:
    - `categories.py` — `GET /categories` (tree), `/{slug}` (detail+breadcrumb), `/{slug}/products` (paginated, `in_stock_only`, `manufacturer_id`, `sort`).
    - `symptoms.py` — list + per-symptom products.
    - `branches.py` — active branches.
    - `products.py` — `GET /products/{slug}` (detail), `/{slug}/related` (substitutes).
    - `search.py` — `GET /search` (with optional auth via `OptionalCurrentUser` for analytics user_id), `/search/suggest`.
    - `BranchIdDep` resolver pinned to `branch_id=1` for MVP single-branch UX (DECISION_LOG'd).
- **DI factories** — `get_search_log_repository`, `get_storefront_catalog_service`, `get_search_service`, `get_storefront_branch_id`.
- **`OptionalCurrentUser`** dep (`app/domain/identity/dependencies.py`) — like `get_current_user` but returns `None` instead of raising on missing/invalid tokens.
- **33 new tests (339 total)**:
    - Integration: `test_storefront_repos.py` (9 — `list_active_tree` excludes inactive; `list_for_category` joins + in-stock filter; sort `price_asc/desc`; symptom join; substitutes (same AI + same dose excludes self); substitute fallback any-dose; suggest prefix; `get_storefront_detail` returns Product + BranchProduct).
    - Unit: `test_search_quality.py` (11 — the 10 PRODUCT §12.1 queries; module-scoped committed fixture seeds Paracetamol/Aspirin/Ibuprofen/Metamizol once); `test_storefront_caching.py` (3 — categories tree caches + invalidates on mutation; product detail invalidates on bp update; `cache_invalidate` no-ops without Redis).
    - E2E: `test_storefront_endpoints.py` (10 — guest tree → category products → symptom products → product detail + related → branches → search + suggest; out-of-stock filter default).
- **`ProductTranslation`** + cached read tweak: `cache_get_or_set` now stores `model_dump(mode="json")` (orjson-friendly); read-side re-validates via Pydantic.
- 339 tests pass; mypy --strict + ruff clean across 81 source files.

#### Phase 6 — Inventory foundation (2026-05-02) — complete

- **4 new tables** in `app/domain/inventory/models.py`: `suppliers`, `branch_products` (composite PK `(branch_id, product_id)` with cached `total_quantity` / `reserved_quantity`), `inventory_batches` (source-of-truth, with **per-batch** `quantity_reserved` for concurrency-safe FEFO), `stock_movements` (append-only audit). Plus `MovementType` `StrEnum`.
- **Migration `896070994c68 — create inventory tables`** — composite indexes for FEFO (`idx_ib_fefo` on `(branch_id, product_id, expiry_date, received_at)`) and reports (`idx_ib_expiry`, `idx_bp_low_stock`); the `chk_movement_sign` CHECK is emitted via `op.execute` for the multi-clause disjunction (Phase 5 discipline). Round-trips clean.
- **5 repositories** in `app/domain/inventory/repositories.py`: `BranchRepository`, `SupplierRepository`, `BranchProductRepository` (composite PK + `get_for_update` + `list_low_stock`), `InventoryBatchRepository` (`list_for_fefo_locked` with `FOR UPDATE SKIP LOCKED` filtering 7-day hard block + per-batch reservation; `list_near_expiry`; `sum_remaining_non_expired` for reconcile), `StockMovementRepository` (append-only + filtered list).
- **`InventoryService`** in `app/domain/inventory/services.py`:
    - `receive_batch` — auto-creates `branch_products` row at `price=0, is_available=False` ("pending pricing"); 7-day hard-block check; super_admin-only override; `is_short_dated` flag for ≤60 days; same-batch-twice → 409; pairs every batch insert with a `received` movement and a cache update inside one transaction.
    - `adjust_batch` — signed `quantity_change`; rejects "below reserved"; writes `damaged` or `adjusted` movement.
    - `allocate_for_order` — FEFO with `FOR UPDATE SKIP LOCKED` + per-batch unreserved-only filter; raises `OutOfStockError` on shortfall; returns `BatchAllocation` plan.
    - `reserve` — applies allocations: increments per-batch `quantity_reserved`, writes `reserved` movements, bumps `bp.reserved_quantity` (does NOT decrement `quantity_remaining` — that moves only at sale).
    - `convert_reservation_to_sold` — flips `reserved` → `sold`, decrements `quantity_remaining` and `total_quantity`.
    - `release_reservations` — pre-dispatch cancel; un-reserves; physical stock untouched.
    - `release_pending_orders` — worker hook (Phase 11 schedules).
    - `reconcile_branch_product` — recomputes cache from sum of batches; safety net.
    - `update_branch_product` — admin pricing / threshold / availability path with audit log.
- **Schemas** in `app/domain/inventory/schemas.py` — request bodies (`BatchReceiveRequest`, `BatchAdjustRequest`, `BranchProductUpdate`), reads (`BatchRead`, `BranchProductRead`, `StockMovementRead`), report rows (`NearExpiryRow`, `LowStockRow`), and `BatchAllocation` (the FEFO planner output Phase 8 will consume).
- **7 admin endpoints** under `/api/admin/v1` (`app/api/admin_v1/inventory.py`):
    - `POST /branches/{id}/inventory/batches` — receive
    - `PATCH /inventory/batches/{batch_id}` — adjust (with reason + signed delta + manual-branch enforcement for non-super)
    - `PATCH /branches/{id}/inventory/products/{product_id}` — pricing / threshold / availability
    - `GET /branches/{id}/inventory` — paginated list with `low_stock` / `only_available` filters
    - `GET /inventory/movements` — audit list with date range / product / branch / type / admin / order filters
    - `GET /branches/{id}/reports/near-expiry?days=30|60|90&format=json|csv` — streaming CSV
    - `GET /branches/{id}/reports/low-stock?format=json|csv` — streaming CSV
- **RBAC**: `super_admin`, `branch_manager`, `pharmacist` allowed; `content_editor` forbidden (403). Per-branch enforcement via composite `_branch_admin` dep that nests `require_role` + `require_branch_access` (the obvious `Annotated[X, Depends(a), Depends(b)]` form silently fires only the last `Depends` — documented in DECISION_LOG).
- **DI**: `app/api/deps.py` adds factories for the 4 new repos + the inventory service.
- **82 new tests (306 total)**:
    - Integration: `test_inventory_repos.py` (10 — UNIQUE batch natural-key collision; `chk_bp_reserved_le_total`; `chk_ib_remaining_le_received`; `chk_ib_reserved_le_remaining`; `chk_movement_sign` rejecting wrong-sign; FEFO ordering; FEFO 7-day exclusion; FEFO unreserved-only filter; low-stock query; near-expiry window; stock_movement append + filter); `test_fefo_concurrent.py` (parameterised: 50 loops by default, env `FEFO_CONCURRENT_LOOPS=100` for nightly; asserts no oversell, no deadlock, no double-spend per batch — the hard concurrency centrepiece).
    - Unit: `test_inventory_service.py` (15 — receive happy path; receive within hard-block rejected; override requires super_admin; short-dated flag; same-batch-twice 409; adjust damaged decrements; adjust below reserved blocked; allocate FEFO splits across batches; insufficient-stock raises; reserve increments + writes movement + leaves remaining unchanged; reservation → sold decrements; release returns to free pool; reconcile corrects drift; bp update; bp not-found).
    - E2E: `test_inventory_admin.py` (7 — pharmacist receives + sees stock; receive within hard block 400; pharmacist adjusts own batch; content_editor 403; branch_manager other-branch 403; low-stock report; near-expiry CSV format).
- **Test factories** in `tests/factories/inventory.py` — `seed_branch`, `seed_supplier`, `seed_branch_product`, `seed_inventory_batch` (in-session) plus committed variants for E2E.
- **Dev fixtures** under `dev/fixtures/inventory/`: `branches.json` (2 — Bishkek Central + Asanbay), `suppliers.json` (2), `batches.json` (7 batches across both branches with mixed expiries to exercise the 60-day soft-warn and FEFO ordering); `seed.py` is idempotent and resolves products by SKU from the catalog seed.

#### Phase 5 — Catalog foundation (2026-05-02) — complete

- **13 catalog/ops tables** in `app/domain/catalog/models.py` and `app/domain/ops/models.py`: `manufacturers`, `active_ingredients` + `active_ingredient_translations`, `categories` + `category_translations`, `symptoms` + `symptom_translations`, `products` + `product_translations` + `product_images`, `product_active_ingredients` (M:N with dosage), `product_symptoms` (M:N), `admin_audit_log`.
- **Migration `5b872d07a987 — create catalog and audit log`:**
    - FULLTEXT index `ftx_pt_search` on `product_translations(name, short_description, description)` `WITH PARSER ngram` — emitted via `op.execute` since SQLAlchemy doesn't render the parser clause.
    - Generated-column trick on `product_images.primary_product_id` enforces "one primary image per product"; `product_images.product_id` FK uses `ON DELETE RESTRICT` (MySQL forbids STORED generated columns from depending on FK-CASCADE columns — same Phase 4 finding).
    - `dosage_unit` CHECK emitted via `op.execute` to avoid SQLAlchemy's `%` → `%%` paramstyle escape.
    - Spec deviation: `categories` self-parent CHECK omitted — MySQL 8.0+ rejects CHECK constraints on AUTO_INCREMENT columns (error 3818). Enforced in the service layer instead (Phase 5.4).
    - Hand-edited from autogen output: removed spurious `ALTER COLUMN ... server_default` noise on existing identity tables; simplified downgrade to `drop_table` per table.
- **Repositories**: `ManufacturerRepository`, `ActiveIngredientRepository`, `CategoryRepository`, `SymptomRepository`, `ProductRepository` (with `get_by_id_with_full` + `fulltext_search`), `AdminAuditLogRepository`.
- **~30 schemas** for Create/Update/Read across all 5 catalog aggregates with nested translations + M:N shapes; `ProductCreate` carries everything for atomic creation; `BulkImportRowError` + `BulkImportSummary`.
- **`SlugService`** (`app/domain/catalog/slug.py`) — Cyrillic transliteration via `python-slugify[unidecode]` (`Панадол 500мг` → `panadol-500mg`); `unique_slug(base, exists)` collision-suffix loop.
- **`AdminAuditLogService`** (`app/domain/ops/services.py`) — single helper Phase 5.4+ services use for every mutation.
- **New dep:** `python-slugify[unidecode]>=8.0,<9.0`.
- **Bulk-import CSV column contract locked** in `BUILD_PROGRESS.md`.
- **`CatalogAdminService`** (`app/domain/catalog/services.py`) — CRUD for the 4 simpler aggregates (manufacturers, ingredients, categories, symptoms) with audit per mutation; `has_active_products` / `has_children` guards on delete; soft-delete via `deleted_at` for categories; replace-semantics on translations on update.
- **`ProductService`** (`app/domain/catalog/products.py`) — atomic `create_product` (translations + ingredients + symptoms in one flush), `update_product` (replace M:N), `soft_delete_product`, `upsert_from_import` returning `(product, created)`.
- **`ProductImageService`** (`app/domain/catalog/images.py`) — synchronous Pillow resize → 4 WebP variants (thumbnail 200, medium 600, large 1200, original capped 2400); EXIF stripped; storage under `IMAGE_STORAGE_DIR/products/<uuid>/<token>/<variant>.webp`; `is_primary` toggle clears other primaries first to honour the generated-column UNIQUE; allowed MIMEs `image/{jpeg,png,webp}`; size cap from `IMAGE_MAX_BYTES` (default 10 MiB).
- **`ProductImportService`** (`app/domain/catalog/import_csv.py`) — CSV-only ≤ 500 rows synchronous; `dry_run` parses + validates references and reports `BulkImportSummary`; `apply` upserts by SKU; ingredient triples `Name:DOSE:UNIT`, semicolon-separated symptom slugs, slash-delimited category paths.
- **5 admin routers** under `/api/admin/v1`: `manufacturers`, `active-ingredients`, `categories`, `symptoms`, `products` (CRUD + `/{id}/images` upload + `/products/import/{dry-run,apply}`); RBAC via `require_role("super_admin", "content_editor")`; audit fields (IP, user-agent) captured from `Request`.
- **DI factories** added to `app/api/deps.py` for all catalog repos + services + audit.
- **`Settings`**: `image_storage_dir`, `image_public_base_url`, `image_max_bytes`.
- **Test factories** (`tests/factories/catalog.py`) — in-session and committed seeders for manufacturers, categories, ingredients, symptoms, products.
- **54 new tests (224 total)**:
    - Integration: `test_catalog_repos.py` (10 — manufacturer/symptom/category list_paginated, product slug + sku uniqueness, generated-column UNIQUE on `product_images.primary_product_id`, `get_by_id_with_full` relationship loading, soft-delete excluded from list); `test_fulltext.py` (2 — index name + `WITH PARSER ngram` smoke via INFORMATION_SCHEMA / SHOW CREATE TABLE).
    - Unit: `test_slug_service.py` (8 — Cyrillic transliteration, hyphenation, collision counter); `test_catalog_service.py` (10 — service-level rules: duplicate-name conflict, has-products guard on delete, replace-translations, auto-slug from translation, has-children guard, slug increment); `test_product_import.py` (8 — dry-run vs apply counts, row errors, abort on errors, max_rows guard, nested category path, manufacturer not found, ingredient + symptom resolution).
    - E2E: `test_catalog_admin.py` (10 — RBAC: branch_manager forbidden; CRUD on the 5 aggregates; duplicate SKU 409; soft-delete invisible to GET); `test_product_import.py` (3 — multipart CSV dry-run + apply + error reporting); `test_product_images.py` (4 — Pillow PNG upload, primary toggle clears prior primary, delete, invalid content-type 400).
- **`ProductRead`** uses `model_validator(mode="before")` to expose `symptom_ids` from the ORM `symptoms` relationship.
- **Dev fixtures** under `dev/fixtures/catalog/` — `manufacturers.json` (7), `categories.json` (6 incl. nested), `ingredients.json` (5), `symptoms.json` (5), `products.json` (5); idempotent `seed.py` (`uv run python -m dev.fixtures.catalog.seed`).
- 224 tests pass; ruff + mypy --strict clean across 70 source files.

#### Phase 4 — Identity & Authentication (2026-05-02)
- **Domain:** identity (`User`, `UserAddress`, `OtpCode`, `AdminUser`, `AdminSession`) + minimal `Branch` model (Phase 6 expands inventory).
- **Migrations:** two new revisions — `drop_ping_placeholder` removes the Phase 2 stand-in; `create_identity_tables` adds 6 tables with the partial-unique generated-column trick on `user_addresses.default_user_id`.
- **Repositories** (5): `UserRepository`, `UserAddressRepository`, `OtpRepository`, `AdminUserRepository`, `AdminSessionRepository`. Plus minimal `BranchRepository` for inventory.
- **Services** (4): `OtpService` (request + verify with 3 rate-limit composes), `AuthService` (JWT refresh rotation + logout), `AccountService` (CRUD + default-toggle handling), `AdminAuthService` (login + 5-attempt lockout + session lookup).
- **Schemas** (13): OtpRequest/Verify, TokenPair, Refresh, Logout, UserMeRead/Update, Address Create/Update/Read, AdminLogin, AdminMeRead. Phone normalisation via `normalise_phone` field validator; `EmailStr` (added `email-validator` dep).
- **Dependencies** (`app/domain/identity/dependencies.py`): `get_current_user` (Bearer JWT), `get_current_admin` (cookie), `require_role(*roles)`, `require_branch_access(param)`, plus `CurrentUser` / `CurrentAdmin` type aliases.
- **DI factories** (`app/api/deps.py`): repositories + services + `TokenIssuer`.
- **SMS abstraction**: `SmsMessage`, `SmsQueue` Protocol (`app/integrations/sms/base.py`), `FakeSmsQueue` that logs and records (`app/integrations/sms/fake.py`). Phase 11 will wire ARQ; Phase 10 lands the real Nikita adapter.
- **Routes**:
  - Customer (`/api/v1/auth`): `POST /otp/request`, `POST /otp/verify`, `POST /refresh`, `POST /logout`.
  - Customer (`/api/v1/me`): `GET`, `PATCH`, `/me/addresses` CRUD (5 endpoints).
  - Admin (`/api/admin/v1/auth`): `POST /login` (sets HttpOnly cookie), `POST /logout`, `GET /me`.
- **52 new tests (170 total)**:
  - Repository: 11 tests in `test_identity_repos.py` — phone uniqueness, address default-uniqueness via generated column, OTP filters (consumed/expired/most-recent), owner-scoped lookup, attempts increment.
  - Service unit: 19 tests — `test_otp_service.py` (8: request/verify happy paths + rate limits + max attempts + expired + consumed-once), `test_auth_service.py` (5: rotate, unknown-jti, expired, logout, idempotent-on-garbage), `test_admin_auth_service.py` (7: success, wrong-pw counter, lockout at 5, reset on success, inactive rejected, token round-trip, logout revokes).
  - E2E: 22 tests — `test_otp_flow.py` (4), `test_otp_edges.py` (4), `test_refresh_logout.py` (3), `test_addresses.py` (4 incl. owner-scoping + default toggle), `test_admin_auth.py` (6).

#### Phase 3 — Core Infrastructure (2026-05-02)
- **Redis client** in `app/core/redis.py` — `init_redis`/`close_redis`/`get_redis` lifecycle, idempotent init, ``decode_responses=True`` so reads come back as ``str``. Wired into FastAPI lifespan.
- **i18n** in `app/core/i18n.py` — `t(key, lang, **vars)` with fallback chain (lang → default → key + warning), variable interpolation via ``str.format``, lazy JSON loading cached in module dict, `clear_translation_cache()` helper for tests.
- **i18n JSON files** seeded from `PRODUCT §21.2` (UI copy library, ~36 keys) + `§21.3` (6 SMS templates): `app/i18n/{ru,ky,en}.json`. RU is complete; KY/EN have UI translations from spec; SMS keys exist only in RU and fall back at runtime.
- **Cache helpers** in `app/core/cache.py` — `cache_get_or_set` (orjson-serialised, miss → loader → write), `invalidate(prefix)` via SCAN + batched DEL, low-level `get_raw`/`set_raw` for opaque storage (used by idempotency).
- **Rate limiter** in `app/core/ratelimit.py` — `hit(key, limit, window_seconds)` using INCR + EXPIRE NX (fixed-window). Returns post-hit count; raises `RateLimitExceededError` over limit. `reset(key)` for tests/admin.
- **Security primitives** in `app/core/security.py`:
    - `hash_password` / `verify_password` — argon2id via passlib (m=65536, t=3, p=2) + appended pepper; `verify_password` returns False on any error (never raises).
    - `hash_otp` / `verify_otp` — HMAC-SHA256 + pepper, ``hmac.compare_digest`` for constant-time verify.
    - `generate_numeric_code(length)` — cryptographically random N-digit string via `secrets`.
    - `normalise_phone(value, default_region="KG")` — E.164 via ``phonenumbers``.
    - `TokenIssuer` — JWT access (15m) + refresh (30d), HS256, header carries `kid="k1"` (rotation scaffold), `jti` from uuid7. `decode(token, expected_type, expected_kind)` validates and rejects mismatches.
    - `TokenPair` dataclass exposes both tokens + their jtis.
- **Idempotency store** in `app/core/idempotency.py` — `body_digest(body) -> sha256 hex`; `check(key, digest, scope="")` returns ``"miss" | "hit_same" | "hit_different"``; `store(key, digest, response, scope="", ttl=86400)` persists in Redis.
- **Pagination** in `app/core/pagination.py` — `PageParams` (Pydantic clamp 1≤page, 1≤page_size≤100), `page_params` FastAPI dep, `offset_limit`, `Page[T]` envelope; `Cursor[T]` envelope with `encode_cursor`/`decode_cursor` (base64url JSON of created_at + id); `parse_sort` with allow-list rejection.
- **Lifespan order** in `app/main.py`: ``configure_logging → init_redis → Sentry init → yield → close_redis → shutdown_complete log``.
- **`RedisDep`** added to `app/api/deps.py` — `Annotated[Redis, Depends(get_redis_dep)]`.
- **31 new tests (118 total)**:
    - Unit: `test_security_password.py` (7), `test_security_otp.py` (8), `test_security_jwt.py` (8 incl. expired/wrong-type/wrong-kind/kid), `test_security_phone.py` (7), `test_pagination.py` (15), `test_i18n.py` (14).
    - Integration (Redis on docker-compose db 15): `test_cache.py` (4), `test_ratelimit.py` (5), `test_idempotency.py` (6), `test_redis_lifecycle.py` (2).

#### Phase 2 — Database Foundation & Alembic (2026-05-02)
- **Async SQLAlchemy engine** in `app/core/db.py` — `AsyncEngine` from `settings.mysql_dsn`, `async_sessionmaker` with `expire_on_commit=False`, `get_db` FastAPI dependency, `session_scope` async context manager for workers/scripts.
- **`GUID` BINARY(16) custom type** in `app/core/types.py` with byte-swapped layout that mirrors MySQL `UUID_TO_BIN(uuid_str, 1)` for B-tree locality. Round-trip verified via 6 unit tests including byte-order assertion against the documented swap.
- **Inline `uuid7()`** in `app/core/types.py` — RFC 9562 UUID v7 (48-bit ms timestamp + version 7 + 12-bit rand_a + variant 0b10 + 62-bit rand_b). No new dep added.
- **Alembic configured for async** — `alembic.ini`, `migrations/env.py` (async-friendly via `async_engine_from_config` + `connection.run_sync`), `migrations/script.py.mako`. `compare_type=True, compare_server_default=True`.
- **First migration** `20260502_0740_init_ping.py` creates the placeholder `ping` table with `mysql_engine='InnoDB'`, `mysql_charset='utf8mb4'`, `mysql_collate='utf8mb4_0900_ai_ci'`. **Will be removed in Phase 4** along with `app/_ping_transient.py`.
- **DB test fixtures** in `tests/conftest.py` — session-scoped `_migrated_db` runs `alembic downgrade base && upgrade head`; per-test `session` fixture uses a fresh `NullPool` engine to dodge the pytest-asyncio function-loop / module-engine mismatch.
- **18 new tests**: `test_guid_type.py` (10 — byte-swap round-trip, byte-order, uuid7 properties), `test_db_charset.py` (5 — utf8mb4, 0900_ai_ci, sql_mode, ngram_token_size=2, InnoDB), `test_db_session.py` (2 — insert/read + Cyrillic round-trip), `test_alembic_smoke.py` (1 — full down/up round-trip via `asyncio.to_thread`).

#### Phase 1 — Project Foundation (2026-05-02)
- **Project metadata.** `pyproject.toml` with full BACKEND §2 dep set (FastAPI 0.115, SQLAlchemy 2.0.36 async, asyncmy 0.2.10, Pydantic 2.9, Alembic 1.14, Redis 5.2, ARQ 0.26, structlog 24.4, orjson 3.10, sentry-sdk 2.18, etc.); ruff + mypy + pytest config. `uv.lock` committed.
- **Local dev infra.** `docker-compose.yml` with `mysql:8.4` + `redis:7-alpine` + profile-gated `mysql-test` (tmpfs, port 3307) and `api`/`worker` (build profile). `Makefile` with 18 targets including `dev`, `worker`, `lint`, `type`, `test`, `docker-up*`, `shell-mysql`, `pre-commit`. Multistage `Dockerfile` (builder → runtime, non-root user, healthcheck).
- **Core infra.** `app/core/config.py` (Settings via pydantic-settings; SecretStr for sensitive fields; CSV parsing for `cors_origins` + `supported_languages` via `NoDecode`). `app/core/errors.py` (full `AppError` hierarchy: Validation, Authentication, PermissionDenied, NotFound, Conflict, RateLimitExceeded, OutOfStock, InvalidOTP, IdempotencyConflict). `app/core/logging.py` (structlog with JSON output, per-request `ContextVar` for `request_id`, PII redaction processor: full-redact for password/code/otp/token/jwt/secret/cookie, phone-mask `+996****NNNN` per PHARMACY §20.4). `app/core/i18n.py` (Accept-Language resolver). `app/core/time.py` (UTC + Asia/Bishkek helpers). `app/core/db_base.py` (`Base`, `TimestampMixin`, `SoftDeleteMixin` using MySQL `DATETIME(fsp=6)`).
- **API layer.** `app/main.py` (FastAPI factory, `lifespan` async ctx mgr, Sentry no-op when DSN absent, ORJSONResponse default). `app/api/middleware.py` (`RequestIdMiddleware`, `AccessLogMiddleware`). `app/api/errors.py` (RFC 7807 Problem Details handlers for `AppError`, `RequestValidationError`, `IntegrityError`, fallback). `app/api/health.py` (`GET /health` → `{"status":"ok","version":"0.1.0"}`). Empty `/api/v1` and `/api/admin/v1` routers ready for Phase 4+.
- **Empty package skeletons.** `app/domain/{identity,catalog,inventory,orders,payments,deliveries,ops}/__init__.py`, `app/integrations/{sms,payments,storage}/__init__.py`, `app/workers/{__init__,settings}.py`, `app/worker.py`, `migrations/{,.gitkeep,versions/.gitkeep}`, test directories.
- **Tests.** 24 tests across 6 files: `tests/conftest.py` (loads `.env.test`, autouse settings-cache reset, `httpx.AsyncClient` fixture), `tests/unit/test_config.py` (5 tests), `tests/unit/test_errors.py` (5 tests including handler integration), `tests/unit/test_logging.py` (8 tests covering redaction + context binding), `tests/integration/test_health.py` (3 tests), `tests/integration/test_request_id.py` (3 tests).
- **CI.** `.github/workflows/ci.yml` — Python 3.12 + uv with cache; brings up `mysql-test` + `redis` via docker-compose; runs `make lint`, `make type`, `make test`.
- **Pre-commit hooks.** `pre-commit-hooks` (trailing whitespace, EOF, YAML/TOML, merge conflict, private key, large files, mixed line ending), `ruff-pre-commit`, `mirrors-mypy`. Installed and ready.
- **README.md.** 5-minute getting-started + daily commands + project layout + spec-pointer table.

### Changed

- `README.md` — replaced 1-line stub with full project overview.

### Deprecated

- (none yet)

### Removed

- (none yet)

### Fixed

- **Spec drift in `BACKEND §25` docker-compose** — removed `--default-authentication-plugin=caching_sha2_password` flag (variable removed in MySQL 8.4 — caused boot failure with `unknown variable` error).
- **Spec disagreement on `sql_mode`** — `BACKEND §25` and `CLAUDE.md` differed; aligned to CLAUDE.md (stricter: STRICT_TRANS_TABLES + ONLY_FULL_GROUP_BY).
- **Spec drift in `BACKEND §6.6`** — `DateTime(6)` is wrong with SQLAlchemy core (`DateTime` takes `timezone: bool` as 1st arg, not fsp). Switched to MySQL dialect's `DATETIME(fsp=6)` for microsecond precision.

### Security

- **PII redaction processor** active from Phase 1 — every structlog event passes through `redact_pii` before JSON serialisation. Sensitive field names (`password`, `code`, `otp`, `token`, `jwt`, `secret`, `api_key`, `authorization`, `cookie`) redacted; phone fields masked to `+996****NNNN`.
- **`SecretStr` on every secret field** in `Settings` — `repr` and `model_dump` never leak the underlying value.
- **Sentry SDK** initialised with `send_default_pii=False`; default scrubbing applies.

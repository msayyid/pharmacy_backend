# BUILD_PLAN.md — Pharmacy Platform Backend

> Master plan produced in Phase 0 by reading the three blueprints end-to-end and `CLAUDE.md`. This document does not invent behaviour; it organises what the specs say into a build sequence, validates each architectural call, and surfaces every place I needed to make a judgement.
>
> **Status:** awaiting human approval before Phase 1 begins.
> **Authored:** 2026-05-02.
> **Spec versions read:** PRODUCT_BLUEPRINT.md (1759 lines, v1.0), PHARMACY_BLUEPRINT_2.md (2133 lines, v1.0 — note filename `_2`; see OPEN_QUESTIONS Q5), BACKEND_BLUEPRINT.md (2879 lines, v1.0), CLAUDE_CODE_PROMPTS.md (3918 lines).

---

## 1. System summary in my own words

A single-pharmacy OTC e-commerce backend for Bishkek, Russian-primary, scaling to multi-branch. Four conceptual pillars dictate the entire design.

**Why FEFO + reservation + snapshot is the design (not three independent ideas, one triplet).** Pharmacy stock has three properties retail stock doesn't: every batch has an expiry date, two customers can race for the last 3 packs of paracetamol, and a six-month-old order must still print the name and price the customer actually paid even after the catalog changed. FEFO ("First Expiry, First Out") solves the first: the FEFO query orders `inventory_batches` by `expiry_date ASC, received_at ASC`, splits across batches if no single batch has enough, and skips anything within the 7-day hard block. Concurrency is solved inside that same query with `FOR UPDATE SKIP LOCKED` — concurrent transactions skip rows another transaction is touching and walk to the next batch, never deadlocking. Reservation is the bridge: at place-order time, batches transition to `reserved` (writing `stock_movements 'reserved'` and incrementing `branch_products.reserved_quantity`); at dispatch, `reserved → sold` (writing `stock_movements 'sold'`, decrementing both `total_quantity` and `reserved_quantity`); at pre-dispatch cancel, `released`. Available stock for the storefront is `total_quantity - reserved_quantity`. Snapshot lives on `order_items` — `product_name_snapshot`, `product_sku_snapshot`, `batch_number_snapshot`, `expiry_date_snapshot`, `unit_price`. These are write-once: the catalog can rename, soft-delete, or reprice the product, but the order keeps what the customer bought. The FK to `inventory_batches` survives separately, which is the recall trail.

**Multi-language as data, not config.** Per-entity translation tables (`product_translations`, `category_translations`, `symptom_translations`, etc.) keyed `UNIQUE (entity_id, language_code)`. RU is mandatory — a product without RU translation is hidden from the storefront entirely; KY/EN are optional with RU fallback. FULLTEXT indexes attach to translation tables, with the MySQL `ngram` parser (`token_size=2`) standing in for the Postgres `tsvector` + trigram combo the original blueprint assumed. User-facing strings never hardcode in code — every string resolves through `t(key, lang, **vars)` against `app/i18n/<lang>.json`. Server returns *codes* (`out_of_stock`, `validation_error`); the frontend resolves the message. This decouples backend deploys from translation churn.

**Two auth systems, deliberately separate.** Customers: phone-OTP login → 15-min JWT access + 30-day rotating refresh, refresh `jti` stored in Redis (allows logout). Admins: email + argon2id password + optional TOTP → server-side session in `admin_sessions`, HttpOnly Secure SameSite=Lax cookie. `get_current_user` and `get_current_admin` are different dependencies that never cross. Authorization is `(role, resource, action, branch_id)` — four roles (`super_admin`, `branch_manager`, `pharmacist`, `content_editor`) with branch scoping for the bottom three.

**Inventory truth in three layers.** `branch_products.total_quantity` is a read-cached aggregate driving the storefront. `inventory_batches.quantity_remaining` is the per-batch source of truth driving FEFO. `stock_movements` is an immutable append-only ledger. Every batch quantity change writes a paired `stock_movements` row in the same transaction — no exceptions, no `UPDATE` shortcuts. Nightly `reconcile_stock_cache` recomputes the aggregate and alerts on drift.

---

## 2. Phase-by-phase build order

Phases mirror `CLAUDE_CODE_PROMPTS.md §5–17`, but the effort/risk read is mine.

| # | Phase | Effort | Risk | Notes |
|---|---|---|---|---|
| 0 | Spec Comprehension & Master Plan | S (this session) | Low | This document. Planning gate before Phase 1. |
| 1 | Project Foundation | M (90–120m) | Low | FastAPI scaffolding, Docker, lint/type/test pipeline, /health. Pure infra. |
| 2 | Database Foundation & Alembic | M (60–90m) | Low–Med | `GUID` type with byte-swap, async engine, mixins, MySQL server config. Easy to get charset/collation wrong; verify with `SHOW VARIABLES`. |
| 3 | Core Infrastructure | M | Low | Redis client, structlog with PII redaction, error hierarchy, rate-limit helper, idempotency store, i18n loader. The structlog redaction processor must catch `phone`, `code`, `otp`, `password`, `token` by name. |
| 4 | Identity & Authentication | L | Med | OTP issue/verify, JWT pair, refresh rotation, admin sessions, RBAC dependencies. Rate-limit edges. The two-auth-systems separation is the single biggest source of subtle bugs in this phase. |
| 5 | Catalog Domain & Admin Catalog API | L | Med | Categories tree, products, translations, ingredients, symptoms, image pipeline integration point (worker is Phase 11). Slug transliteration RU→Latin needs care. |
| 6 | Inventory Domain & Admin Inventory API | L | Med | `branch_products`, `inventory_batches`, `stock_movements`, FEFO query (without using it for orders yet — that's Phase 8). Receive-stock workflow with 7-day-warning override. |
| 7 | Customer Discovery (Browse & Search) | L | Med–High | FULLTEXT + ngram + synonym dictionary + ranking. Quality risk: ngram on Cyrillic with `token_size=2` produces false positives. Test with the §12.1 query bank from PRODUCT. |
| 8 | Cart, Checkout & Place-Order (FEFO) | XL | High | The crown jewel. Place-order transaction = atomic FEFO allocation + `order_items` snapshot insert + reservation + status-history + idempotency check. Concurrency tests (`asyncio.gather`, ≥50× repeat). |
| 9 | Admin Order Lifecycle, Reports & Audit | L | Med | State-machine in code (single source of truth), picking screen API, reservation→sold transition on dispatch, audit log writes on every admin mutation. |
| 10 | Integrations: SMS, Payments, Storage | M | Med | One folder per integration (`base.py` + `real.py` + `fake.py` + `factory.py`). Nikita SMS contract; Freedom Pay (Phase 1.5 not MVP — confirm scope); R2 image upload. Webhook signature verification for payments. |
| 11 | Background Jobs (ARQ) | M | Med | Worker registry, cron jobs (UTC times — document KG offset everywhere), idempotent jobs, image-resize pipeline, near-expiry / low-stock daily reports. |
| 12 | Hardening & Launch Readiness | L | Med | OWASP audit, load testing, runbooks, backup/restore drill, smoke recipes for every feature, BACKEND §27 + PRODUCT §26 walk-through. |

Total ~14–18 focused sessions.

---

## 3. Critical path

```
0 → 1 → 2 → 3 → 4 ┬→ 5 ┬→ 7 → 8 → 9 → 12
                  └→ 6 ┘     ↑
                              │
                              10 (SMS feeds Phase 4 and 8; payments feed 8)
                              11 (jobs: cron jobs depend on 5/6/8 entities)
```

**Hard sequencing:**
- 4 must be done before 8 (place-order needs `get_current_user`).
- 5 and 6 can be parallelised by sub-agents within a single session if scope allows; in practice 6 leans on the `Product` model from 5, so do 5 first.
- 7 needs both 5 (catalog) and 6 (`branch_products.total_quantity` for the "in stock" filter).
- 8 needs 5, 6, and 4. This is the bottleneck phase.
- 10 (SMS) is needed by 4 (OTP send) and 9 (status SMS) — but the `fake.py` adapter lets 4 and 9 ship without the real provider. Real provider can land late.
- 11 cron jobs are decoupled — `expire_batches`, `reconcile_stock_cache`, `release_pending_orders` need 6 + 8 entities; `near_expiry_report` needs 6.

**Soft slack:** if a phase blows past its estimate, splitting into `Phase N.1`, `Phase N.2` per the CLAUDE.md "no single response touches more than 5 files" rule is preferred over rushing.

---

## 4. Architecture validation

For each spec recommendation, I either endorse or push back with reasoning. No silent disagreements.

### 4.1 Endorsed without modification

| Recommendation | Why I endorse |
|---|---|
| FastAPI + SQLAlchemy 2.x async + MySQL 8 + Redis + ARQ (`BACKEND §2`) | Coherent async stack; MySQL choice trades the Postgres FTS niceties for AsyncMy maturity and ops familiarity. |
| `BINARY(16)` byte-swapped UUIDs via `GUID` type (`BACKEND §6.2, §7.2`) | Byte-swap matches `UUID_TO_BIN(_, 1)` for B-tree locality; UUID7 generation app-side keeps inserts time-ordered. |
| `expire_on_commit=False` + `lazy="raise"` (`BACKEND §7, §8`) | Forces explicit loading; prevents `MissingGreenlet` at response serialisation. |
| Single-app monolith with two router prefixes (`BACKEND §13`) | PHARMACY §14.4 hints at two deployable apps — overkill for MVP. Single app, two prefixes, separate later if scaling demands. |
| ARQ over Celery (`BACKEND §17`) | Async-native, simpler ops. Celery's heft is unjustified for MVP load. |
| Idempotency stored in Redis, not MySQL (`BACKEND §21`) | Keeps OLTP DB lean; 24h TTL covers any reasonable retry window. |
| Customer JWT + admin session (`BACKEND §14`) | Different revocation needs. Customer JWT with rotating refresh + Redis `jti` = revocable enough; admin session = instant revocation. |
| RFC 7807 Problem Details for errors (`BACKEND §15`) | Standard, machine-readable. Pairs cleanly with the code/i18n split. |
| Server returns codes; frontend resolves messages (`CLAUDE.md` decision) | Decouples backend deploys from translation files. |
| Snapshot on `order_items` (`PHARMACY §7.4`, `PRODUCT §5`, `CLAUDE.md` invariant) | Sacred invariant. Order history must survive catalog mutation. |
| FEFO + 7-day hard block + 30-day shelf-at-dispatch as three separate layers (`PRODUCT §5.5`, `CLAUDE.md`) | Defence in depth. See OPEN_QUESTIONS Q1 for the 30-day enforcement layer. |

### 4.2 Endorsed with operational caveats

**MySQL `FULLTEXT` + `ngram` parser as Postgres FTS replacement (`BACKEND §6.4`).** Endorse for MVP, but `ngram_token_size=2` on Cyrillic produces false positives — *every* 2-character Cyrillic substring matches. The blueprint already flags graduating to Meilisearch sooner than the PG plan suggested. Add: monitor `search_log` zero-result rate AND a "low-quality-result" signal (top result has `score < threshold`). If quality complaints surface in Phase 7 testing, raise to `token_size=3` first (cheaper than swapping engines). Document the tuning in `DECISION_LOG`.

**Generated-column trick for "partial unique" (`BACKEND §6.5`).** Endorse but verify SQLAlchemy `Computed(..., persisted=True)` emits the right MySQL DDL in Alembic autogenerate — if not, the constraint goes in a manual `op.execute`. Smoke test at Phase 2.

**Single VPS for production (`PHARMACY §22.2`).** Endorse for MVP launch. Add: backup-restore drill in Phase 12 — "backups are only real when proven to restore." Migration to managed Postgres-style HA is in the scaling roadmap; MVP ships with the single-VPS reality and a documented 10-min snapshot-restore RTO.

**Django admin reuse (`PHARMACY §14.3`).** **Push back.** This recommendation is in PHARMACY but is contradicted by the chosen FastAPI stack in BACKEND. There is no Django admin in scope. Admin UI is a separate frontend project (per CLAUDE.md "Frontend is a separate project, not yours"). The backend exposes `admin_v1` JSON API; the frontend choice is out of scope for this build. **No code impact**, but flag the ambiguity so future me doesn't try to wire Django admin in.

### 4.3 Pushed back — recommend deviation

**Recommendation (`PHARMACY §10.3`, `PRODUCT §12.4`): synonyms in `symptom_translations.synonyms text[]`.** MySQL has no array type. Push back: store as `JSON NOT NULL DEFAULT (JSON_ARRAY())` and read into Python list at the application layer. Same shape; standard MySQL idiom. Captured in OPEN_QUESTIONS Q8 as a confirmation, but proposed default is JSON.

**Recommendation (implicit in `PHARMACY §16` Postgres-flavoured): `python-jose` for JWT (`BACKEND §2`).** Push back softly. `python-jose` has had slow maintenance and historical CVEs. PyJWT is the actively maintained alternative. **Proposed default for now: keep `python-jose` per spec, but log this as a risk and revisit at Phase 4** when we wire JWT for real. If a CVE drops between now and then, we switch. See OPEN_QUESTIONS Q6 + RISK #7.

**Recommendation (`PRODUCT §11.4`): cold-chain summer surcharge as Phase 2.** Endorse the deferral, but verify schema readiness — `orders.delivery_fee` is a single column. When Phase 2 lands the surcharge becomes part of `delivery_fee` calculation. **No new column needed; do not preemptively add `cold_chain_surcharge_amount`.** Captured in OPEN_QUESTIONS Q2.

**Recommendation (`PHARMACY §11.4` pseudo-code uses SERIALIZABLE/REPEATABLE READ).** Push back on isolation level: MySQL's default `REPEATABLE READ` is right; SERIALIZABLE has a perf cost and `FOR UPDATE SKIP LOCKED` already gives us the strict ordering on the contended rows. Use default isolation + `FOR UPDATE SKIP LOCKED`. Document in DECISION_LOG at Phase 8.

### 4.4 Open architectural calls (decisions deferred)

These reach OPEN_QUESTIONS.md with a proposed default. Each blocks a specific phase if unresolved.

- **30-day shelf-at-dispatch enforcement layer** — Phase 8.
- **COD high-value floor (>10,000 KGS)** — Phase 8.
- **Refresh-token storage final form** — Phase 4.
- **Reservation timeout cron cadence** — Phase 11.
- **Bishkek city-match string normalisation** — Phase 8.

---

## 5. Tech stack inventory & version currency

`BACKEND §2` pins majors with floats inside. Today's date is 2026-05-02; the assistant knowledge cutoff is January 2026. Every dependency below is at minimum what was current as of cutoff; later patch releases are accepted.

| Package | Pinned | Currency | Compat risk |
|---|---|---|---|
| `fastapi` | `>=0.115,<0.116` | Current (Nov 2024); 0.116+ likely shipped by May 2026 | Low — pin allows patches; consider widening to `<0.118` at Phase 12. |
| `uvicorn[standard]` | `>=0.32,<0.33` | Current | Low |
| `gunicorn` | `>=23.0,<24.0` | Current | Low |
| `sqlalchemy[asyncio]` | `>=2.0.36,<2.1` | Current; 2.0.x is stable | Low |
| `asyncmy` | `>=0.2.10,<0.3` | Latest of `0.2.x`; `0.3.x` may have breaking changes | **Med** — verify 0.3.x release notes before any future bump. Maintained by `long2ice`. Less battle-tested than `aiomysql` historically; faster on MySQL 8 features. |
| `alembic` | `>=1.14,<1.15` | Current | Low |
| `pydantic` | `>=2.9,<3.0` | Current; 2.10+ exists | Low |
| `pydantic-settings` | `>=2.6,<3.0` | Current | Low |
| `python-jose[cryptography]` | `>=3.3,<4.0` | **Quasi-stagnant; prior CVEs.** | **High concern** — see RISK #7 + OPEN_QUESTIONS Q6. Alternative: PyJWT. |
| `passlib[argon2]` | `>=1.7.4,<2.0` | 1.7.x is the long-stable line. Project has had infrequent releases. | Med — `argon2-cffi` (also pinned) is the modern direct alternative. Acceptable. |
| `argon2-cffi` | `>=23.1,<24.0` | Current | Low |
| `redis` | `>=5.2,<6.0` | Current | Low |
| `arq` | `>=0.26,<0.27` | Current; maintained but slow cadence | Low–Med — flag at Phase 11; if maintenance lapses, Celery fallback is the migration target per `BACKEND §17.1`. |
| `httpx` | `>=0.27,<0.28` | Current | Low |
| `python-multipart` | `>=0.0.18,<0.1` | Current; known to evolve fast | Low |
| `structlog` | `>=24.4,<25.0` | Current | Low |
| `orjson` | `>=3.10,<4.0` | Current | Low |
| `tenacity` | `>=9.0,<10.0` | Current | Low |
| `phonenumbers` | `>=8.13,<9.0` | Current; library updates monthly with metadata | Low — keep on auto-update for metadata correctness. |
| `boto3` | `>=1.35,<2.0` | Current | Low |
| `pillow` | `>=11.0,<12.0` | Current | Low |
| `sentry-sdk[fastapi]` | `>=2.18,<3.0` | Current | Low |

**Build/dev:** `pytest 8.3`, `pytest-asyncio 0.24`, `pytest-cov 6.0`, `ruff 0.8`, `mypy 1.13`, `pre-commit 4.0`, `factory-boy 3.3`, `freezegun 1.5`, `asgi-lifespan 2.1` — all current as of cutoff.

**Runtime:** Python 3.12 (target), MySQL 8.4, Redis 7. All in `docker-compose.yml`.

**Action items from the inventory:**
1. Phase 4 — confirm `python-jose` is still fit for purpose; if not, swap to PyJWT and update `BACKEND §2`.
2. Phase 11 — confirm `arq` upstream is still active.
3. Pre-Phase-1 — run `uv sync` against the pinned set to catch any resolver issues; the spec is comprehensive but resolver edge cases happen.

---

## 6. Build-time conventions Phase 0 already commits to

These come from `CLAUDE.md` and are non-negotiable across every phase. Restated here so future-me doesn't need to rediscover:

- **No expired stock to customer, ever.** FEFO + 7-day block + 30-day shelf-at-dispatch all apply.
- **`order_items` snapshots are immutable.** No update, no exception.
- **Every batch quantity change writes a paired `stock_movements` row in the same transaction.**
- **Customer auth and admin auth never cross.**
- **PII never logs in plaintext.** structlog redaction processor catches `phone`, `code`, `otp`, `password`, `token`.
- **`/specs/*.md` are read-only during build phases.**
- **No partial-pack sales, no scarcity UX, no marketing SMS, no medical advice.**
- **Conventional Commits, Plan-before-implement, BACKEND §27 + PRODUCT §26 gate every phase.**

---

## 7. What's not in this plan (and why)

**Frontend** — explicitly out of scope per `CLAUDE.md`. Backend is the deliverable; frontend is a separate project.

**Real third-party integration testing in Phase 0** — every integration ships with a `fake.py` adapter so phases can land before the real Nikita / Freedom Pay / R2 contracts are wired. Real-provider verification happens in Phase 10.

**Performance load testing** — deferred to Phase 12. The MVP traffic shape is small; correctness matters far more than micro-optimisation. Indexes are designed in §9 of PHARMACY; we trust those until measured otherwise.

**Multi-branch UI** — schema is multi-branch from day one; UI hides branch selector at MVP per `PRODUCT §3.2`.

**Subscriptions / loyalty / promotions / reviews / push / native apps** — `PRODUCT §23.3+` future work. Not built. Schema seams designed-for in `PHARMACY §25`.

---

## 8. Hand-off summary

This plan, the supporting `BUILD_PROGRESS.md`, `OPEN_QUESTIONS.md`, `RISKS.md`, and bootstrapped `DECISION_LOG.md` + `CHANGELOG.md` are the Phase 0 deliverables. Top three open questions blocking Phase 1 are highlighted in chat for human review.

**Phase 1 will not begin until the human says "Plan approved. Proceed to Phase 1."**

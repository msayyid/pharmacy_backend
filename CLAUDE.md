# CLAUDE.md

> Every Claude Code session reads this file first. Read it. Re-read it on resume. It is the project's rulebook.

---

## What this project is

A pharmacy e-commerce platform for Kyrgyzstan. Bishkek-launched, multi-branch ready, OTC-only catalog (no Rx workflow), Russian-primary with Kyrgyz/English support, phone-first mobile users, COD + card payments.

**You are building the backend.** FastAPI + SQLAlchemy 2.x async + MySQL 8 + Redis + ARQ. Frontend is a separate project, not yours.

**Single source of truth for everything: `/specs`.** Four files, in this order of precedence when they disagree:

| File | Wins on | Use for |
|---|---|---|
| `/specs/PRODUCT_BLUEPRINT.md` | User-visible behaviour, business rules | Features, edge cases, copy, journeys |
| `/specs/PHARMACY_BLUEPRINT.md` | Data shape | Schema, indexes, query patterns |
| `/specs/BACKEND_BLUEPRINT.md` | Implementation | Code structure, libraries, patterns |
| `/specs/CLAUDE_CODE_PROMPTS.md` | Build sequence | Phased prompts, meta-prompts, templates |

When the three disagree: **PRODUCT** wins on behaviour, **BACKEND** wins on implementation, **PHARMACY** wins on data shape. Anything not in the specs is an open question — log it in `OPEN_QUESTIONS.md`, propose a default, ask.

---

## Session protocol — do this every session

**At session start:**
1. Read `BUILD_PROGRESS.md` — find the active phase and what's next.
2. Read the last 5 entries of `CHANGELOG.md` and `DECISION_LOG.md`.
3. Read `OPEN_QUESTIONS.md`.
4. Run `make test` to confirm the current state is green. If red, that's the first task.
5. Locate the active phase prompt in `CLAUDE_CODE_PROMPTS.md` and re-read it.
6. Re-read the spec sections cited by the active phase prompt.

**Only then start work.**

**At session end (or phase boundary):**
1. Update `BUILD_PROGRESS.md` — mark progress, note next action.
2. Update `CHANGELOG.md` — under `[Unreleased]`, in Keep a Changelog format.
3. Update `DECISION_LOG.md` — if any non-obvious decision was made.
4. Update `OPEN_QUESTIONS.md` — close resolved questions, add new ones.
5. Commit with Conventional Commits format.
6. Post a one-paragraph summary in chat: what shipped, what's next, anything blocking.

---

## Operating principles

1. **Read specs before you code.** Skimming a 2,000-line spec is how you build the wrong thing.
2. **Plan before you implement.** Every phase has a planning gate. Don't skip it. Wait for plan approval.
3. **Stay in scope.** Each phase has explicit "out of scope" items. If a thought begins with "while I'm here," stop and add to backlog.
4. **Test as you build.** Tests are part of the phase, not a final-week task.
5. **Senior engineer judgment.** If a spec instruction looks wrong, *say so* before implementing. Don't silently work around it.
6. **Surface ambiguity, don't paper over it.** `OPEN_QUESTIONS.md` is for this.
7. **No silent assumptions.** Defaults you invent get logged in `DECISION_LOG.md`.
8. **Run before declaring done.** Code that wasn't executed isn't done.
9. **Conventional Commits, always.** `type(scope): subject` — see §Commits below.
10. **The two checklists are gates.** `BACKEND §27` and `PRODUCT §26` must pass before any phase is "done."

---

## Mechanical overrides — anti-decay rules

> Principles tell you how to think. These rules tell you what to do, mechanically, every time. They exist because LLM failure modes are predictable: context decays, tool results truncate, edits fail silently, and "should work" turns into "doesn't." These rules close those holes.
>
> **These are not suggestions. They override convenience.**

### Pre-work

**Step 0 — Dead code first.** Before any structural refactor on a file >300 lines: remove unused imports, commented-out code, dead helper functions, leftover `print()` / `breakpoint()` calls, and `TODO` comments without an issue link. Commit this cleanup separately. Dead code accelerates context compaction and obscures the structural change you're actually trying to make.

**Re-read the file before editing.** Always. Especially after any of these:
- 10+ messages have passed in the session
- A sub-agent has just run
- A different file in the same module was edited recently
- Auto-compaction may have occurred (you don't know when it does)

The cost of re-reading is seconds. The cost of editing against stale state is broken commits and silent state corruption.

### Phased execution within a session

**No single response touches more than 5 files.** If a task requires more, split into sub-phases or sub-agents, and state the boundary explicitly:

> "Phase 5.1 of 5.3 — touching `models.py`, `repository.py`, `service.py`, `schemas.py`, `routes.py`. Awaiting approval before continuing to Phase 5.2 (admin endpoints)."

This is not bureaucracy. Multi-file changes in a single response produce inconsistencies that slip through review.

**Sub-agent swarming is required for >5 independent files.** When a task fans out to many files with disjoint concerns (e.g., "audit every domain for missing audit-log writes"), launch parallel sub-agents via the Task tool — 5–8 files per agent, 1 agent per concern. Sequential processing of a wide-fan task burns context and produces drift.

Pattern that works:
> "Spawn three sub-agents in parallel:
> Agent A: audit `app/domain/identity/` for missing `admin_audit_log` writes.
> Agent B: same for `app/domain/catalog/`.
> Agent C: same for `app/domain/inventory/` + `app/domain/orders/`.
> Each returns a punchlist. I'll synthesise."

### Forced verification — before claiming complete

You are FORBIDDEN from reporting a task complete until you have:

- [ ] `make test` passes (no new skips, except gated-on-creds tests)
- [ ] `make type` clean (mypy `--strict`)
- [ ] `make lint` clean (ruff)
- [ ] For migration changes: `make migrate` runs cleanly, and `alembic downgrade -1 && alembic upgrade head` round-trips
- [ ] For new endpoints: at least one E2E test passes against them
- [ ] For phase boundaries: the smoke recipe in `BUILD_PROGRESS.md` for that phase runs end-to-end against a fresh DB
- [ ] For changes to background jobs: the job is run manually (force-trigger) and produces expected output

If a check is genuinely impossible (e.g., real SMS sandbox unavailable), state explicitly which check was skipped and why. **Never** say "the test should pass" or "this should work" — run it.

If a tool to run these checks isn't available in your environment (no shell, no `bash_tool`), say so explicitly. Do not claim verification you didn't do.

### Migration & smoke-recipe integrity

After modifying any model, the migration must apply forward and reverse cleanly. After modifying any endpoint, the OpenAPI schema must still validate (FastAPI generates it; check `/openapi.json` parses). After modifying any phase's flow, the smoke recipe in `BUILD_PROGRESS.md` for that phase must still produce the expected output. **A model without a working migration is incomplete. An endpoint without a passing E2E test is incomplete.**

### Edit safety

**Re-read before AND after every `str_replace`/`create_file`.**

- Before: confirm the exact bytes you'll match are still there. The `str_replace` tool fails when `old_string` doesn't match — sometimes it fails loudly, sometimes silently if the diff is tricky.
- After: read the changed region to confirm the edit landed correctly.

**Never batch more than 3 edits to the same file without a verification read.** After 3 edits, re-read the whole file (or a generous range around your changes) before continuing.

### Rename safety — Python is treacherous for renames

You have grep, not an AST. When renaming a class, function, constant, table, column, or relationship, search **separately** for ALL of:

1. Direct references and attribute access — `grep -rn "OldName"`
2. Imports — `from x import OldName` AND `import x` followed by `x.OldName`
3. Type hints in signatures, `Mapped[T]`, `list[T]`, generics
4. String literals — Pydantic `Field(examples=...)`, OpenAPI tags, route names, error codes, log messages
5. Test fixtures and `conftest.py`
6. Alembic migration files — table names, column names, `op.f(...)` constraint names
7. The four `/specs/*.md` files — renames of canonical concepts (e.g., `branch_products`, `inventory_batches`) need spec updates too
8. The i18n JSON files (`ru.json`, `ky.json`, `en.json`) — only if the rename touches a user-facing key
9. `BUILD_PROGRESS.md`, `DECISION_LOG.md`, `CHANGELOG.md` smoke recipes referencing the old name

A single grep does NOT catch all of these. Each one can hide references the others miss.

For database renames specifically, the migration must include both the rename AND data preservation. Never `DROP` and `CREATE` when you mean `RENAME`.

### The senior-engineer override

If you spot architectural debt while working on something else — duplicated state, leaky abstractions, inconsistent patterns, a model that should be split — *propose the fix in chat*. Do **NOT** silently rewrite files outside the current phase's scope.

The bar: would a senior backend engineer who ships Stripe-quality APIs reject this in code review? If yes, surface it. Capture it in `BUILD_PROGRESS.md > Backlog` if it's not urgent. Don't fix it without approval.

The corollary: if you're asked to do X and you discover that doing X requires fixing Y first, **stop and surface it**. Don't build X on top of broken Y.

### Context decay awareness

Long sessions silently compact. By message ~30, your memory of files and decisions made earlier in the session may be stale or wrong. Symptoms:
- You "remember" a function signature that turns out to differ from the actual code
- You skip re-reading because "I just looked at it"
- You're confident about a value (port number, env var name, table name) that turns out wrong

When you notice ANY of these, treat it as a flashing red light:
1. Re-read `BUILD_PROGRESS.md`, the relevant spec sections, and the file in question.
2. Confirm your assumption against current source.
3. If you've been editing against stale memory, check git diff and consider reverting that work.

### Tool result blindness

Tool outputs over ~50,000 characters get silently truncated. If a `grep`, `find`, or `view` returns suspiciously few hits — or you see a result that looks like it ends mid-line, mid-file, or in the middle of a list — assume truncation. Re-run with narrower scope (smaller `view_range`, more specific glob, restricted directory). State explicitly when you suspect truncation occurred.

### File read budget

Read files in chunks for anything over 500 lines. Use `view_range=[start, end]` in 500-line windows. Never assume a single read showed you the full file — most spec files in this project are 1,500–3,900 lines. The `CLAUDE_CODE_PROMPTS.md` file alone is ~3,900 lines.

### No fake data outside tests

Never seed development or fixture data with placeholder strings (`name='Test Product'`, `phone='+1234567890'`, `address='123 Test St'`). Use real Bishkek addresses (`мкр Асанбай, дом 12, кв 45`), real Cyrillic medicine names (`Парацетамол 500мг 12 таб`), real KG mobile prefixes (`+996 700`, `+996 770`, `+996 550`).

Generic placeholders hide bugs that real data exposes — Cyrillic encoding, sort order, character-class assumptions, length validation, FULLTEXT ngram behaviour, slug transliteration. The fixtures in `dev/fixtures/` exist for exactly this reason; reach for them first.

In test code (where determinism matters), real-shaped data is still preferred over `'foo'`/`'bar'`. Use builders / factories that produce realistic values by default.

### i18n keys are law

Never hardcode user-visible strings in code. Always use `t(key, lang, **vars)`. If a key doesn't exist, add it to **all three** language files (`app/i18n/ru.json` mandatory, `ky.json`, `en.json`) BEFORE using it. The same applies to SMS templates, error codes resolved by frontend, and admin notification text.

Server-side errors return a `code`, never a message. The frontend resolves the message. (Decision logged in `DECISION_LOG.md`.)

### Stdlib + agreed libraries first

Use stdlib and the libraries listed in `BACKEND §2` before reaching for new dependencies. If `httpx` solves it, don't pull in `requests`. If `pydantic.EmailStr` works, don't write a regex. If Alembic autogen handles a migration, don't hand-write SQL.

A new top-level dependency requires:
1. Justification in the chat (why none of the existing libs fit).
2. An entry in `DECISION_LOG.md`.
3. An update to `BACKEND §2`'s pinned-versions list.
4. The smallest possible package that does the job (no `numpy` to multiply two numbers).

### Sacred invariants — never compromised, regardless of context

These rules cannot be overridden by clever code, expedience, or seemingly-clean refactors. If you find yourself reasoning "but in this case it's fine to…" — stop. It's not.

1. **No expired stock reaches a customer.** FEFO + 7-day hard block + 30-day shelf-life-at-dispatch. All three apply, always.
2. **`order_items` snapshots are immutable after order creation.** No exceptions. Not even "to fix a typo."
3. **Every batch quantity change writes a paired `stock_movements` row in the same transaction.** No `UPDATE branch_products SET total_quantity = ...` without a movement.
4. **Authentication paths do not mix.** `get_current_user` (JWT) and `get_current_admin` (session) are separate. A token from one never authorises the other.
5. **PII never logs in plaintext.** Phone, OTP, password, JWT, refresh token. The structlog redaction processor catches named fields; don't sneak around it.
6. **`/specs/*` files are read-only during build phases.** Specs evolve through deliberate human decision, never silent edits during implementation.

If a refactor or fix appears to require violating any of these — **stop and surface it**. The invariant is right; your approach needs to change.

---

## Tech stack reality checks

These are the things easy to forget — keep them top of mind.

### Database is **MySQL 8**, not PostgreSQL

The PHARMACY_BLUEPRINT was originally PG-flavoured. The BACKEND_BLUEPRINT §6 documents every adaptation. Re-read §6 before writing any model or migration.

- Charset: `utf8mb4` with `utf8mb4_0900_ai_ci` collation. Server-level + table-level + column-level. Verify with `SHOW VARIABLES LIKE 'character_set%'` and `SHOW VARIABLES LIKE 'collation%'`.
- `sql_mode` includes `STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ONLY_FULL_GROUP_BY,ERROR_FOR_DIVISION_BY_ZERO`.
- UUIDs are `BINARY(16)` via the `GUID` type in `app/core/types.py` — **byte-swapped** for B-tree locality (matches MySQL's `UUID_TO_BIN(_, 1)`). Don't shortcut to `CHAR(36)`.
- No partial unique indexes — use the generated-column trick (BACKEND §6.5). Example: "one default address per user" and "one primary image per product."
- FULLTEXT search uses **ngram parser** for Cyrillic. `ngram_token_size=2` set at server level. Index is created via raw `op.execute` in migrations.
- `FOR UPDATE SKIP LOCKED` is supported on 8.0+. Use it for FEFO allocation.
- `ON UPDATE CURRENT_TIMESTAMP(6)` for `updated_at` — but mixin handles this; don't sprinkle it manually.
- Migrations use `mysql_engine='InnoDB'`, `mysql_charset='utf8mb4'`, `mysql_collate='utf8mb4_0900_ai_ci'` in `__table_args__`.

### Async everything

- All DB calls async (`AsyncSession`). All external calls async (httpx).
- No `time.sleep` — use `asyncio.sleep`.
- No sync DB drivers. asyncmy only.
- `expire_on_commit=False` on the session (already set; don't change it).
- Test fixtures use `pytest-asyncio` with `asyncio_mode=auto`.

### Pydantic v2

- `model_config = ConfigDict(...)`, not `class Config`.
- `field_validator` and `model_validator`, not `validator`.
- `.model_dump()`, not `.dict()`.

### Auth: two systems, do not mix

- **Customers:** SMS-OTP login → JWT access (15min) + refresh (30d, rotating). Refresh `jti` stored in Redis with TTL.
- **Admins:** email + password (argon2id) + optional TOTP → server-side session. Token hash in `admin_sessions`. HttpOnly Secure SameSite=Lax cookie.
- `get_current_user` and `get_current_admin` are **separate** dependencies. Never use one for the other.
- Token `kind` claim discriminates access vs refresh. Reject wrong-kind explicitly.

### Cache, jobs, observability

- Redis 7+, single instance, used for: rate limiting, cache, refresh-token jti, idempotency keys, ARQ queue.
- ARQ for background jobs. NOT Celery. NOT RQ. ARQ.
- structlog with JSON output. Every log line carries `request_id`. PII fields auto-redacted (`password`, `code`, `token`, `otp`).
- ORJSONResponse is the default response class.
- Sentry initialized in both `app/main.py` and `app/worker.py`.

---

## Domain reality checks

The pharmacy-specific rules that, if violated, ship a broken product.

### Stock truth

`branch_products.total_quantity` is a **cached aggregate** of `inventory_batches.quantity_remaining` across non-expired batches. Every write that changes batches updates the cache **in the same transaction**. The nightly `reconcile_stock_cache` job is a safety net, not the primary mechanism.

Available stock = `total_quantity - reserved_quantity`. This is what storefront and cart-validation use.

### FEFO is law

When fulfilling an order line:
1. Pick batches with the **earliest `expiry_date` first**, tie-break by earliest `received_at`.
2. May split across multiple batches.
3. Skip batches with `expiry_date <= CURRENT_DATE + 7 days` (the hard block).
4. Skip batches with `quantity_remaining = 0`.
5. Use `FOR UPDATE SKIP LOCKED` so concurrent orders pick non-overlapping batches.

If you find yourself writing a query that returns "any batch" — stop, that's not FEFO.

### Expiry rules

- `> 60` days: normal sale.
- `30–60` days: normal sale, admin sees daily report.
- `8–29` days: sold only if `allow_short_dated` toggled on the batch.
- `≤ 7` days: **hard block** from sale. FEFO query excludes them. `total_quantity` excludes them.
- `≤ 0`: never visible to anyone except the expired-stock report.

A customer-shipped item must have **≥ 30 days** shelf life remaining at dispatch (PRODUCT §5.5). This is stricter than the 7-day hard block — both apply.

### Reservation lifecycle

```
order placed       → 'reserved' movement, reserved_quantity++
order ready/dispatch → 'sold' movement, total_quantity--, reserved_quantity--
order cancelled (pre-dispatch) → 'released' movement, reserved_quantity--
order refused at door → 'received' movement (restock to original batch), reserved_quantity stays 0
order delivered → refunded → status flip only, NO restock (medicine not resold)
```

Every state transition that affects stock writes a `stock_movements` row in the same transaction. No exceptions.

### Snapshots are immutable

`order_items` snapshots `product_name`, `product_sku`, `batch_number`, `expiry_date`, and the line price/total at order placement. These are write-once. If the underlying product is renamed, deleted, or reprice — the order still shows what the customer bought. **Never** update snapshot fields after order creation.

### Order state machine

`pending → confirmed → preparing → (ready_for_pickup | out_for_delivery) → delivered`. Plus `cancelled` from any pre-delivered state. Plus `delivered → refunded` (admin only). Anything else is a bug.

The transitions table lives in code (`app/domain/orders/lifecycle.py`) as a single source of truth. Don't hand-code transition rules in 10 places.

### Hard product rules

- **No expired sale, ever.** FEFO + 7-day block enforces this.
- **No partial-pack sales.** A pack of 10 sells as 10, not 4.
- **No reviews on medicine.** Cosmetics/devices may get them in Phase 3; medicine never.
- **No symptom-to-medicine prescription.** Symptom *navigation* is fine ("products commonly bought for headache"). Symptom *prescription* ("take this for that") is forbidden.
- **No "only N left" scarcity UX.** We show in-stock or out-of-stock, never quantity.
- **No marketing SMS.** Transactional only.
- **No partial fulfillment without customer approval.** Admin calls; customer chooses.

---

## Localization

- **Russian (RU) is mandatory.** A product without RU translation is hidden from the storefront.
- Kyrgyz (KY) is encouraged; falls back to RU if missing.
- English (EN) is optional; small expat market.
- Phone format: `+996` followed by 9 digits. Store as E.164.
- Currency: **KGS**. Display as `сом` in RU/KY UI, `KGS` in EN UI. No decimals on display by default (whole сом).
- Dates: `DD.MM.YYYY` (RU/KY), `DD/MM/YYYY` (EN), or `YYYY-MM-DD` in admin.
- Timezone: **Asia/Bishkek** (UTC+6, no DST). Internally store UTC. ARQ cron: `06:00 KG = 00:00 UTC`. Document this in code comments to prevent future-you confusion.
- Addresses are free-text + landmark, not street-structured. Bishkek addresses don't fit Western forms (microdistricts, "ориентир: …").
- All user-facing copy comes from `app/i18n/<lang>.json` keyed per `PRODUCT §21`. **Never hardcode user-visible strings.**

---

## File layout

```
/specs/                        # specs (read-only)
  PRODUCT_BLUEPRINT.md
  PHARMACY_BLUEPRINT.md
  BACKEND_BLUEPRINT.md
  CLAUDE_CODE_PROMPTS.md

/app/
  main.py                      # FastAPI app factory
  worker.py                    # ARQ worker entrypoint
  core/                        # cross-cutting infra (no domain logic)
    config.py types.py db.py db_base.py errors.py logging.py
    security.py ratelimit.py cache.py pagination.py i18n.py
    redis.py time.py idempotency.py
  domain/
    identity/                  # users, addresses, otp, admin
    catalog/                   # categories, products, ingredients, symptoms
    inventory/                 # branches, suppliers, batches, movements
    orders/                    # carts, orders, lifecycle
    ops/                       # audit log, sms log, search log
    reports/
  api/
    deps.py
    v1/                        # customer API
    admin_v1/                  # admin API
    webhooks/                  # payment webhooks etc
  integrations/
    sms/ payments/ storage/    # one folder each: base.py, real.py, fake.py, factory.py
  workers/                     # ARQ job functions
  i18n/                        # ru.json, ky.json, en.json, synonyms_ru.json

/migrations/                   # Alembic
/tests/
  unit/ integration/ e2e/ fixtures/
/dev/fixtures/                 # seed data for dev DB
/docs/
  adr/                         # architecture decision records
  runbooks/                    # deploy, rollback, backups, incidents

/CLAUDE.md                     # this file
/BUILD_PROGRESS.md             # current state across sessions
/DECISION_LOG.md               # non-obvious choices
/CHANGELOG.md                  # Keep a Changelog format
/OPEN_QUESTIONS.md             # unresolved ambiguities
/RISKS.md                      # active risks
/Makefile  /docker-compose.yml  /pyproject.toml
```

**Where things go:**
- Domain logic in `app/domain/<context>/` — models, repositories, services, schemas.
- Routes in `app/api/v1/` (customer) or `app/api/admin_v1/` (admin), thin — only HTTP concerns.
- Cross-cutting infra in `app/core/`. **Never** put domain logic here.
- Integrations behind a Protocol; real + fake implementations side-by-side.

---

## Code conventions

### Layering — hard rule

```
api  →  domain (services → repositories → models)  →  core
```

API layer never touches repositories directly. Services orchestrate. Repositories are thin and **never commit** (services own transactions). Core is dependency-free of domain.

### Naming

- snake_case for files, modules, functions, variables.
- PascalCase for classes (models, schemas, services).
- SCREAMING_SNAKE_CASE for constants.
- Tables: plural snake_case (`product_translations`).
- Endpoints: kebab-case in URLs (`/admin/orders/start-preparing`).
- Schemas: `XxxCreate`, `XxxUpdate`, `XxxRead` triplet.
- Models: singular (`Product`, `OrderItem`).
- Errors: `XxxError` ending in Error.

### Types

mypy `--strict` is on. Type hints everywhere, including return types. `from __future__ import annotations` at the top of every module. `Mapped[T]` for SQLAlchemy 2.x columns.

### Errors

- Raise specific exceptions from `app/core/errors.py`. Never raise bare `Exception`.
- User-facing errors carry a `code` (machine-readable) and HTTP status. Frontend resolves the message via i18n key.
- Server returns codes; localised text resolution is the frontend's job (decision logged in DECISION_LOG).
- Log unexpected errors with `request_id` and enough context. PII fields are auto-redacted by structlog processor.

### Async / DB

- Handlers are `async def`. No sync DB calls.
- Repositories never call `commit()`. Services do, via the `get_db` dependency that auto-commits on success and rolls back on exception.
- Use `selectinload` for to-many, `joinedload` for to-one. **Never** rely on lazy loading in handlers — set `lazy="raise"` on relationships in production-critical models.
- Long transactions are a smell. The place-order transaction is the longest acceptable; everything else should be tight.

### i18n

- Every user-facing string comes from `app/i18n/<lang>.json` via `t(key, lang, **vars)`.
- Add new keys to all three files (ru/ky/en). RU is mandatory; KY/EN can stub with RU + a `TODO` marker.
- Server-side errors return a code; frontend resolves the message. Don't translate server-side.

---

## Testing rules

- **Repository tests** hit a real MySQL container. They prove SQL-level correctness.
- **Service tests** mock repositories. They prove orchestration logic.
- **E2E tests** exercise the full HTTP stack via `httpx.AsyncClient`. At least one happy-path E2E per feature.
- **Concurrency tests** for FEFO, place-order, idempotency. Use `asyncio.gather` to fire concurrent operations; assert no oversell, no deadlock. Run in a loop (≥ 50x) in CI to catch flakes.
- **Deterministic only.** No reliance on system clock (use `freezegun` or inject a clock). No reliance on dict ordering. No flaky external calls — use the `fake.py` adapters.
- Coverage target: ≥ 85% on `app/domain` and `app/api`. Coverage isn't quality, but a coverage drop is a smell.
- Skip-marked tests must have a reason and an issue link. No silently disabled tests.

---

## Persistent state files — your memory across sessions

These files matter as much as the code. Update them religiously.

| File | Purpose | When updated |
|---|---|---|
| `BUILD_PROGRESS.md` | Current phase, smoke recipes, backlog | Every phase boundary |
| `DECISION_LOG.md` | Non-obvious choices and rationale | When a decision is made |
| `CHANGELOG.md` | Human-readable history (Keep a Changelog) | Every phase boundary |
| `OPEN_QUESTIONS.md` | Unresolved ambiguities + proposed defaults | When ambiguity surfaces / resolves |
| `RISKS.md` | Active risks with mitigation | When new risk identified |
| `docs/adr/NNNN-*.md` | Architecture decisions worth persisting | Major architectural calls |

Templates for each: `CLAUDE_CODE_PROMPTS.md §23`.

---

## Commits, PRs, and branches

**Conventional Commits** — `type(scope): subject`:

```
feat(auth): add OTP request endpoint with per-phone rate limiting
fix(orders): release stock reservation on customer cancel
refactor(catalog): extract slug generation to SlugService
test(inventory): add concurrent FEFO allocation test
docs(adr): record decision to use byte-swapped UUIDs
build(deps): bump asyncmy to 0.2.10
```

**Body explains WHY**, the diff explains WHAT. Reference feature IDs and spec sections in the body when applicable.

**One feature per branch.** Branch name `phase-N-short-description` or `fix/short-description`. Squash-merge.

**PR template** lives at `.github/pull_request_template.md`. Fill it out — the DoD checklist is not decorative.

---

## Commands cheatsheet

```bash
# setup
make install              # uv sync
docker compose up -d mysql redis

# development
make dev                  # uvicorn with reload
make worker               # ARQ worker
make migrate              # alembic upgrade head
make revision m="msg"     # alembic revision --autogenerate

# quality
make lint                 # ruff check + format check
make type                 # mypy --strict
make test                 # pytest
make test-fast            # unit only
make test-e2e             # full stack
make pre-commit           # run all hooks

# admin
make seed                 # load dev fixtures
make shell-mysql          # mysql client
make shell-redis          # redis-cli
```

---

## Hard prohibitions — things to **never** do

1. **Never** sell expired stock. The 7-day hard block + FEFO query enforce it; don't add code paths that bypass.
2. **Never** mutate `order_items` snapshots after creation.
3. **Never** commit without a corresponding `stock_movements` row when batch quantities change.
4. **Never** use `lazy="select"` (default) on production models without `selectinload`/`joinedload` in the query — N+1 will reach you.
5. **Never** log PII in plaintext (phone, OTP code, password, JWT). The structlog redaction processor catches the named fields; don't sneak around it with custom keys.
6. **Never** accept user input into a SQL string. Parameter binding only.
7. **Never** auto-suggest a medicine for a symptom in a way that looks like medical advice. Symptom navigation only.
8. **Never** add a "low stock" indicator that exposes operational data ("only 2 left").
9. **Never** ship a feature listed as Phase 1.5+ in `PRODUCT §23` without explicit instruction. Even if "easy."
10. **Never** invent behaviour when specs are silent. Add to `OPEN_QUESTIONS.md` and ask.
11. **Never** weaken `mypy --strict`, `ruff`, or test coverage to "ship the phase." Fix the code instead.
12. **Never** modify `/specs/*` files without explicit instruction. Specs evolve through human decision, not silent edits.
13. **Never** use Celery, RQ, or APScheduler. ARQ is the choice.
14. **Never** install a new top-level dependency without logging the choice in `DECISION_LOG.md` and updating `BACKEND §2`.

---

## Tool usage

### Use deep thinking when

- Designing a transaction with concurrency concerns (the place-order FEFO is the canonical example).
- Choosing between two architectural options.
- Tracing a subtle bug — especially anything stock-related or ordering-related.
- Considering whether to deviate from a spec.

### Use sub-agents (Task tool) when

- A phase has independent research streams (e.g., "research Nikita SMS API current contract" + "scaffold the SMS adapter").
- You need to read a large body of code that would blow your main context.
- Two parts of the work touch disjoint files.

Don't use them for sequential work or work that touches the same files.

### Use web search when

- A library version may have changed since training (FastAPI, SQLAlchemy, Alembic, asyncmy, ARQ, Pydantic, phonenumbers, passlib).
- You're integrating a third-party API (Nikita, Freedom Pay, Cloudflare R2) and need current contracts.
- A library error message hints at a known issue.

Don't search for general Python knowledge or domain content — the specs cover the domain.

### Use TodoWrite

At the start of every phase. Break the phase into 6–15 trackable items. Mark in-progress and complete as you go. Recovery point if the session is interrupted.

---

## When you're unsure

| Situation | What to do |
|---|---|
| Specs disagree | Apply the precedence rule (PRODUCT > behaviour, BACKEND > impl, PHARMACY > data). If still unclear, log in `OPEN_QUESTIONS.md` and ask. |
| Specs silent on a case | Add to `OPEN_QUESTIONS.md` with a proposed default. Continue with the default; mark in `DECISION_LOG.md` as "pending confirmation." |
| Spec instruction looks wrong | Don't silently fix. Surface it in chat with the reasoning, and ask. |
| Library behaviour different from training data | Web search current docs. Verify with a test. |
| You hit a class of bug not covered by tests | Add a regression test. Add to `RISKS.md` if it's a class. |
| Plan starts to feel too large | The phase is too large. Split it. Don't power through. |
| Sub-agent returns conflicting info | You synthesise; cite both sources; pick one with reasoning logged in `DECISION_LOG.md`. |
| Tests pass but you don't trust the code | Trust the instinct. Read again. Add tests for the case you're worried about. |
| `str_replace` fails on `old_string` not matching | Re-read the file. Don't retry blindly with a slightly different string — the file may have changed since you last saw it. |
| Search/grep returns 0 or suspiciously few hits | Assume tool truncation or wrong scope. Re-run with a narrower path or smaller window. State the suspicion. |
| You can't remember if you already edited a file in this session | You probably did, and your mental model is stale. Re-read it. |
| You feel "this should work" without running it | Run it. The phrase "should work" is forbidden in completion claims. |
| You catch yourself touching a 6th file in one response | Stop. Split. State the boundary explicitly and await approval. |
| You're tempted to fix something outside the phase | Add it to backlog in `BUILD_PROGRESS.md`. Surface it in chat. Don't silently expand scope. |

---

## Status: where we are

> Update this section at every phase boundary. Future-you reads this first.

- **Active phase:** Phase 0 — Spec Comprehension & Master Plan (or whichever phase is in progress)
- **Last shipped:** (none yet — fresh repo)
- **Next milestone:** Approved master plan; then Phase 1.

For the canonical state, read `BUILD_PROGRESS.md`. This section is a pointer.

---

## When something hurts

If you find yourself:
- Pasting the same code in three places — extract.
- Adding a third special-case branch — re-think the abstraction.
- Writing a comment to explain something tricky — first try renaming things until the comment isn't needed.
- Working around a spec rather than implementing it — stop and surface.
- Skipping tests because "this part is obvious" — write the test anyway; you'll thank yourself.
- Making the same decision more than once — write an ADR.

---

*This file is the project's rulebook. Re-read on every session start. If something is wrong here, fix it — but log the change in `DECISION_LOG.md` and `CHANGELOG.md`. Future Claude sessions and future humans depend on it.*

# Build Progress

> Persistent state between sessions. Update at every phase boundary.
> If you can't tell what's next from this file, it's wrong — fix it.

## Current state

- **Active phase:** Phase 7 — Customer Discovery (Browse & Search) _(complete)_
- **Status:** **complete** — 339 tests pass; mypy --strict clean across 81 source files.
- **Last session:** 2026-05-02
- **Sub-phases done:** 7.1 (search_log table + synonyms JSON), 7.2 (storefront repo methods incl. composite-ranked search), 7.3 (storefront schemas + StorefrontCatalogService + SearchService), 7.4 (cache invalidation hooks + DI), 7.5 (categories/symptoms/branches routes), 7.6 (products/search routes + router), 7.7 (33 new tests across repo / search quality / caching / e2e), 7.8 (hand-off + commit).
- **Next session should:** start Phase 8 — Cart, Checkout & Place-Order (FEFO). Re-read `PRODUCT §7.1–7.2, §11`, `PHARMACY §7.1–7.2, §11.4`, `BACKEND §15` (idempotency). Phase 8 will reuse `InventoryService.allocate_for_order` + `reserve` from Phase 6 inside the place-order transaction.

## Phases

- [x] Phase 0 — Spec Comprehension & Master Plan _(done 2026-05-02)_
- [x] Phase 1 — Project Foundation _(done 2026-05-02)_
- [x] Phase 2 — Database Foundation & Alembic _(done 2026-05-02)_
- [x] Phase 3 — Core Infrastructure _(done 2026-05-02)_
- [x] Phase 4 — Identity & Authentication _(done 2026-05-02)_
- [x] Phase 5 — Catalog Domain & Admin Catalog API _(done 2026-05-02)_
- [x] Phase 6 — Inventory Domain & Admin Inventory API _(done 2026-05-02)_
- [x] Phase 7 — Customer Discovery (Browse & Search) _(done 2026-05-02)_
- [ ] Phase 7 — Customer Discovery (Browse & Search)
- [ ] Phase 8 — Cart, Checkout & Place-Order (FEFO)
- [ ] Phase 9 — Admin Order Lifecycle, Reports & Audit
- [ ] Phase 10 — Integrations: SMS, Payments, Storage
- [ ] Phase 11 — Background Jobs & Scheduled Tasks
- [ ] Phase 12 — Hardening & Launch Readiness

## Smoke test recipes

> Concrete commands that prove the system works at each milestone.
> Update as new flows ship. None are runnable yet — recipes pre-seeded from the spec for future-me to fill in.

### After Phase 1 (verified 2026-05-02)

```bash
brew install uv                        # one-time on macOS
make install                           # uv sync — Python 3.12 + all deps into .venv
make docker-up                         # mysql:8.4 + redis:7-alpine; healthy in ~25s
make dev &                             # uvicorn on :8000 with reload
curl localhost:8000/health
# → {"status":"ok","version":"0.1.0"}
curl -H "X-Request-ID: my-rid" -i localhost:8000/health
# → 200 with x-request-id: my-rid echoed back
make lint && make type && make test    # 0 issues, 24 tests pass
make pre-commit                        # hooks installed and clean
```

### After Phase 2 (placeholder)

```bash
make migrate                                # alembic upgrade head
alembic downgrade -1 && alembic upgrade head  # round-trip
make shell-mysql                            # SHOW VARIABLES LIKE 'character_set%'
                                            # → utf8mb4 across the board
```

### After Phase 2 (verified 2026-05-02)

```bash
make docker-up-test                                # mysql-test on :3307 + redis
set -a && source .env.test && set +a
uv run alembic upgrade head                        # creates ping table via migration
uv run alembic downgrade base && uv run alembic upgrade head   # round-trip
docker compose exec -T mysql-test mysql -utest -ptest pharmacy_test \
  -e "SHOW CREATE TABLE ping\G"                    # asserts InnoDB + utf8mb4 + 0900_ai_ci
make test                                          # 42 tests pass (24 Phase 1 + 18 Phase 2)
make lint && make type                             # both clean
```

### After Phase 3 (verified 2026-05-02)

```bash
make docker-up-test                                # mysql-test :3307 + redis :6379
set -a && source .env.test && set +a

# i18n
uv run python -c "from app.core.i18n import t; \
  print(t('auth.otp.title','ru')); \
  print(t('auth.otp.title','ky')); \
  print(t('sms.otp','en',code='123456'))"          # KY/EN-missing → falls back to RU

# security primitives
uv run python -c "from app.core.security import normalise_phone, generate_numeric_code; \
  print(normalise_phone('+996 700 12 34 56')); \
  print(generate_numeric_code(6))"

# tests
make lint && make type && make test                # all green; 118 tests pass
```

### After Phase 4 (verified 2026-05-02)

```bash
make docker-up-test                                   # mysql-test :3307 + redis :6379
set -a && source .env.test && set +a
uv run alembic upgrade head                           # 3 migrations apply

uv run uvicorn app.main:app --port 8765 --log-level info > /tmp/uvicorn.log 2>&1 &

# OTP request
curl -s -X POST -H "Content-Type: application/json" \
  -d '{"phone":"+996700123456"}' \
  http://localhost:8765/api/v1/auth/otp/request
# → {"sent":true,"expires_in_seconds":300}

# Pull OTP code from log (FakeSmsQueue logs it as JSON)
CODE=$(grep "sms_enqueued" /tmp/uvicorn.log | tail -1 \
  | python3 -c "import sys,json,re; d=json.loads(sys.stdin.read()); m=re.search(r'(\d{4,})',d['body']); print(m.group(1))")

# Verify → tokens
RESP=$(curl -s -X POST -H "Content-Type: application/json" \
  -d "{\"phone\":\"+996700123456\",\"code\":\"$CODE\"}" \
  http://localhost:8765/api/v1/auth/otp/verify)
ACCESS=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
REFRESH=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['refresh_token'])")

# /me
curl -s -H "Authorization: Bearer $ACCESS" http://localhost:8765/api/v1/me
# → {"id":"...","phone":"+996700123456","preferred_language":"ru","is_phone_verified":true,...}

# Refresh rotates; old refresh now fails
curl -s -X POST -H "Content-Type: application/json" \
  -d "{\"refresh_token\":\"$REFRESH\"}" \
  http://localhost:8765/api/v1/auth/refresh
# → new pair

curl -s -X POST -H "Content-Type: application/json" \
  -d "{\"refresh_token\":\"$REFRESH\"}" \
  http://localhost:8765/api/v1/auth/refresh
# → 401 refresh_revoked

make test               # 170 tests pass (118 from Phases 1–3 + 52 new in Phase 4)
make lint && make type  # both clean
```

### After Phase 6 (verified 2026-05-02)

```bash
make docker-up-test                                  # mysql-test :3307 + redis
set -a && source .env.test && set +a
uv run alembic upgrade head                          # 5 migrations: ping, drop-ping,
                                                      #   identity, catalog, inventory
uv run alembic downgrade -1 && uv run alembic upgrade head   # round-trip clean

# Seed: catalog first (needed for product FKs), then inventory.
uv run python -m dev.fixtures.catalog.seed
uv run python -m dev.fixtures.inventory.seed
# → "Seeded 2 branches, 2 suppliers, N branch_products, M inventory_batches"

# Service-level FEFO smoke (mock-as-if-Phase-8). Receive 100 of Panadol
# at branch 1, allocate 10, confirm remaining = 90 in cache + free pool.
uv run python -c "
import asyncio
from app.core.config import get_settings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy import select
from app.domain.inventory.models import BranchProduct, InventoryBatch
from app.domain.catalog.models import Product

async def main():
    s = get_settings()
    eng = create_async_engine(str(s.mysql_dsn), poolclass=NullPool)
    async with async_sessionmaker(eng)() as ses:
        p = (await ses.execute(select(Product).where(Product.sku=='PAR-500-20'))).scalar_one()
        bp = (await ses.execute(select(BranchProduct).where(BranchProduct.product_id==p.id))).scalars().first()
        b = (await ses.execute(select(InventoryBatch).where(InventoryBatch.product_id==p.id))).scalars().first()
        print(f'Panadol: bp.total={bp.total_quantity} bp.reserved={bp.reserved_quantity} batch.qty_remaining={b.quantity_remaining}')
asyncio.run(main())"

# Concurrent FEFO smoke
FEFO_CONCURRENT_LOOPS=50 uv run pytest tests/integration/test_fefo_concurrent.py
# → 50 passed (no oversell, no deadlock, no double-spend)

make test                # 306 tests pass (224 prior + 82 in Phase 6)
make lint && make type   # both clean
```

### After Phase 7 (verified 2026-05-02)

```bash
make docker-up-test                                  # mysql-test :3307 + redis
set -a && source .env.test && set +a
uv run alembic upgrade head                          # 6 migrations now (+ search_log)

# Seed full storefront so curl returns rows.
uv run python -m dev.fixtures.catalog.seed
uv run python -m dev.fixtures.inventory.seed

uv run uvicorn app.main:app --port 8765 > /tmp/uvicorn.log 2>&1 &
sleep 1

# Categories tree
curl -s http://localhost:8765/api/v1/categories -H "Accept-Language: ru" | head -c 200

# Product detail
curl -s http://localhost:8765/api/v1/products/par-500-20 -H "Accept-Language: ru" | head -c 300

# Search — the 10 PRODUCT §12.1 queries (each must return paracetamol):
for q in 'парацетамол' 'пара' 'парацитамол' 'paracetamol' 'от головы' \
         'жаропонижающее' 'панадол' 'головная боль' 'температура' 'анальгин'; do
  echo "== $q"
  curl -s -G "http://localhost:8765/api/v1/search" --data-urlencode "q=$q" \
    -H "Accept-Language: ru" | python3 -m json.tool | head -20
done

# Suggest
curl -sG http://localhost:8765/api/v1/search/suggest --data-urlencode 'q=пара' \
  -H "Accept-Language: ru" | python3 -m json.tool

# Branches list
curl -s http://localhost:8765/api/v1/branches | python3 -m json.tool

make test                # 339 tests pass (306 prior + 33 new in Phase 7)
make lint && make type   # both clean
```

### After Phase 8 (placeholder — extends Phase 4)

```bash
# Browse, add to cart, checkout COD
curl localhost:8000/api/v1/categories
curl -X POST localhost:8000/api/v1/cart/items \
  -H "Authorization: Bearer $ACCESS" \
  -d '{"product_id":"...","quantity":2}'
curl -X POST localhost:8000/api/v1/checkout/place \
  -H "Authorization: Bearer $ACCESS" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"address_id":1,"payment_method":"cash_on_delivery","delivery_method":"delivery"}'
# → {order_number: "PH-2026-000001", payment_redirect_url: null}
```

### After Phase 12

Add: "smoke recipe runs against a fresh DB end-to-end" and the OWASP audit checklist signed off.

## Bulk-import CSV column contract (Phase 5)

> Locked in Phase 5.3 per `CLAUDE_CODE_PROMPTS` Phase 5 spec. The
> ``ProductImportService`` (Phase 5.5) reads exactly these columns. Changes
> require a phase-boundary decision in `DECISION_LOG.md`.

```
sku                       (required, unique)
barcode                   (optional)
slug                      (optional — auto-generated from name_ru if absent)
manufacturer              (optional — string match against manufacturers.name)
category_path             (required — slash-delimited slug chain, e.g. "analgesics/paracetamol")
form                      (required — one of the ProductForm enum values)
pack_size_label           (optional)
pack_quantity             (optional, decimal)
pack_unit                 (optional)
requires_prescription     (optional, boolean — "true"/"false"/"1"/"0"; default false)
min_age                   (optional, int)
max_per_order             (optional, int)
weight_grams              (optional, int)
requires_cold_chain       (optional, boolean; default false)
storage_temp_min_c        (optional, int)
storage_temp_max_c        (optional, int)
is_active                 (optional, boolean; default true)
is_featured               (optional, boolean; default false)
name_ru                   (recommended — RU mandatory for storefront visibility)
name_ky                   (optional)
name_en                   (optional)
short_description_ru      (optional)
short_description_ky      (optional)
short_description_en      (optional)
description_ru            (optional)
description_ky            (optional)
description_en            (optional)
active_ingredients        (optional — semicolon-separated triples
                           "Paracetamol:500:mg;Caffeine:50:mg")
symptoms                  (optional — semicolon-separated symptom slugs:
                           "headache;fever")
```

**Idempotency:** rows are matched by ``sku``. Existing SKUs are updated
(translations + M:N replaced; never deleted by import). New SKUs inserted.
Missing SKUs in the file are NEVER deleted. Phase 5 limits ≤ 500 rows
synchronously; ≥ 501 returns 413 ("use the worker — Phase 11").

## Backlog (deferred items)

> Things noticed during Phase 0 reading that are out of MVP scope or non-urgent. Move to a phase backlog or to `OPEN_QUESTIONS.md` when they become decisions.

- [x] ~~Phase 4 cleanup of `app/_ping_transient.py`~~ — done 2026-05-02 (Phase 4.1 dropped the table + deleted the file).
- [ ] **TOTP enforcement** — `admin_users.mfa_secret` column exists but Phase 4 does not verify TOTP codes. Add `pyotp` dep + verification logic when MFA enrolment UX lands (Phase 1.5+).
- [ ] **Phone change flow** — deferred per `PRODUCT §17.3` (Phase 1.5).
- [ ] Cyrillic synonym table (Soviet-era brand names → modern INN, e.g. `анальгин → метамизол`) — content seed in Phase 5 or Phase 7. Bishkek-specific must-haves: `анальгин`, `цитрамон`, `аспирин-кардио`. Coverage: at least 50 brand→ingredient pairs by launch.
- [ ] Recall workflow as a real feature with `recalled` flag on batches — surfaced in `PRODUCT §5.6` as Phase 2; for MVP, recall = manual `damaged` movement with reason "recall: <batch_number>". Add to Phase 2 backlog.
- [ ] Reservation timeout job cadence — see OPEN_QUESTIONS Q11. Default plan: single ARQ cron every 5 min checking both 24h-pending and 30min-card thresholds. Confirm at Phase 11.
- [ ] `python-jose` → PyJWT migration evaluation — Phase 4 review point. RISK #7.
- [ ] Meilisearch graduation criteria — already in PHARMACY §10.5. Add monitoring at Phase 7: zero-result rate > 5% sustained, or p95 search latency > 200 ms, triggers the migration plan.
- [ ] `PHARMACY_BLUEPRINT_2.md` filename normalisation — see OPEN_QUESTIONS Q5. Defer to user.
- [ ] Marketing SMS opt-out granularity — `PRODUCT §14.5` Phase 2.
- [ ] Customer-facing "best before YYYY-MM-DD" on product page (vs admin-only at MVP) — `PRODUCT §15.3` Phase 2.
- [ ] Right-to-be-forgotten — `PRODUCT §20.2` Phase 2 / 3. Schema seams: soft-delete user, hash phone/name on retained orders.

## Active blockers

- None for Phase 2.
- **Resolved this phase:** Q6 (`python-jose` retained — see DECISION_LOG); Q9 (refresh token = JWT-encoded + jti in Redis — implemented).
- **Open questions remaining:** Q1 (30-day shelf-at-dispatch — Phase 8); Q3 (COD high-value floor — Phase 8); Q5 (filename — cosmetic); Q11 (reservation timeout cron — Phase 11); Q12 (Bishkek city match — Phase 8). Q8 (synonym JSON) confirmed.

## In-progress TodoWrite items

> Synced from active session. Cleared when phase completes.

(none — Phase 1 list cleared at hand-off; Phase 2 list lands when the next session opens its plan.)

# Build Progress

> Persistent state between sessions. Update at every phase boundary.
> If you can't tell what's next from this file, it's wrong — fix it.

## Current state

- **Active phase:** Phase 2 — Database Foundation & Alembic
- **Status:** done
- **Last session:** 2026-05-02
- **Next session should:** open `CLAUDE_CODE_PROMPTS.md §8` (Phase 3 — Core Infrastructure). Run the plan-first gate: re-read `BACKEND §3 (core/), §14.6 (security helpers), §16 (middleware), §18 (caching/Redis), §21 (idempotency)` before producing the Phase 3 plan.

## Phases

- [x] Phase 0 — Spec Comprehension & Master Plan _(done 2026-05-02)_
- [x] Phase 1 — Project Foundation _(done 2026-05-02)_
- [x] Phase 2 — Database Foundation & Alembic _(done 2026-05-02)_
- [ ] Phase 3 — Core Infrastructure
- [ ] Phase 4 — Identity & Authentication
- [ ] Phase 5 — Catalog Domain & Admin Catalog API
- [ ] Phase 6 — Inventory Domain & Admin Inventory API
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

### After Phase 4 (placeholder — from §23.1 of CLAUDE_CODE_PROMPTS)

```bash
curl -X POST localhost:8000/api/v1/auth/otp/request \
  -H 'Content-Type: application/json' \
  -d '{"phone":"+996700123456"}'
# read OTP from log (fake provider), then:
curl -X POST localhost:8000/api/v1/auth/otp/verify \
  -H 'Content-Type: application/json' \
  -d '{"phone":"+996700123456","code":"123456"}'
# → {access_token, refresh_token}
curl localhost:8000/api/v1/me \
  -H "Authorization: Bearer $ACCESS"
# → user profile, language ru
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

## Backlog (deferred items)

> Things noticed during Phase 0 reading that are out of MVP scope or non-urgent. Move to a phase backlog or to `OPEN_QUESTIONS.md` when they become decisions.

- [ ] **Phase 4 cleanup of `app/_ping_transient.py`** — delete the file, remove its import line in `migrations/env.py`, write a `DROP TABLE ping` migration. The placeholder shipped in Phase 2 to seed the migration pipeline.
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
- **Open questions touching Phase 2:** Q8 (synonym storage shape — JSON vs junction table) is decided as JSON for now; revisit if junction admin UX becomes painful. Q5 (filename) still cosmetic. Q6 (`python-jose` vs PyJWT) still deferred to Phase 4.

## In-progress TodoWrite items

> Synced from active session. Cleared when phase completes.

(none — Phase 1 list cleared at hand-off; Phase 2 list lands when the next session opens its plan.)

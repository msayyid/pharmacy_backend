# Architecture (One-page)

> Snapshot of the running system at v1.0.0-rc1. Canonical detail lives in
> `/specs/{PRODUCT,PHARMACY,BACKEND}_BLUEPRINT.md` + `CLAUDE.md`.

## Stack

- **Web**: FastAPI 0.115, async/await throughout (no sync I/O on request paths).
- **DB**: MySQL 8.4, accessed via SQLAlchemy 2.x async with `asyncmy`. UUIDs are
  `BINARY(16)` byte-swapped via `app/core/types.GUID` for B-tree locality
  (matches `UUID_TO_BIN(_, 1)`).
- **Cache + queue**: Redis 7+ — rate limiting, cache, refresh-token jti store,
  webhook dedupe, ARQ broker.
- **Worker**: ARQ — scheduled crons + on-demand jobs. Single queue, `max_jobs=10`.
- **External**: Nikita SMS (scaffold), Freedom Pay (scaffold), Cloudflare R2
  (scaffold). All real adapters block on vendor docs (OPEN_QUESTIONS Q13/Q14/Q15);
  fakes carry every test.

## Layering

```
api/           HTTP, FastAPI routers (v1/ customer + admin_v1/ admin + webhooks/)
  ↓
domain/        bounded contexts (identity, catalog, inventory, orders, deliveries,
               payments, ops, reports). Each has models / repositories /
               services / schemas.
  ↓
core/          cross-cutting infra (config, db, redis, security, errors,
               logging, pagination, i18n, time, types, idempotency, metrics).
  ↑
integrations/  external-service adapters (sms/, payments/, storage/) —
               Protocol + real + fake + factory per provider.
workers/       ARQ entrypoint + job functions (sms, images, imports,
               scheduled, run_once).
```

**Hard rule**: `api → domain → core`. API never touches repositories directly;
services orchestrate; repositories are thin and never commit (services own
transactions via the `get_db` dependency).

## Persistence shape

- **Schema migrations**: `migrations/versions/` (Alembic, async). 9 migrations
  through Phase 11. Round-trip clean (`downgrade -1 && upgrade head`).
- **Reference data**: `dev/fixtures/` — catalog (manufacturers, categories,
  ingredients, symptoms, products) + inventory (branches, suppliers, batches).
  Idempotent re-runnable seeders.
- **Stock truth**: `inventory_batches.quantity_remaining` is the source of
  truth; `branch_products.total_quantity` is a cached aggregate. Every batch
  mutation pairs with a `stock_movements` row in the same transaction (sacred
  invariant). `reconcile_stock_cache` cron fixes drift nightly.

## Order lifecycle (single source of truth)

`app/domain/orders/lifecycle.py:ALLOWED_TRANSITIONS` — config dict driving
every admin status transition. Each entry has `allowed_roles`,
`requires_reason`, and `on_success` side-effect hooks (release reservation /
convert reserved→sold / restock for refused-at-door / record courier / refund
Payment row). Customer-visible transitions trigger SMS via
`SMS_TEMPLATE_FOR_STATUS`.

## Background jobs (Phase 11)

- **On-demand**: `send_sms`, `process_image_upload`, `process_product_import`.
- **Cron** (KG→UTC mappings inline; audit test enforces): near_expiry_report
  (06:00 KG), low_stock_report (06:10), expire_batches (02:00),
  reconcile_stock_cache (03:00), cleanup_otps (04:00), cleanup_carts (04:10),
  release_pending_orders (every 5 min — handles both 24h-pending + 30min-card
  thresholds), payment_reconcile (every 5 min, offset 2).

## Observability (Phase 12)

- **`/health`** — liveness, no I/O.
- **`/health/ready`** — readiness probe (DB SELECT 1 + Redis PING; 503 on any
  failure with structured body).
- **`/metrics`** — Prometheus exposition, bearer-token guarded
  (`METRICS_TOKEN`). Module-local `CollectorRegistry` keeps third-party
  counters out.
- **structlog** — JSON output; PII redacted at the processor layer (phone
  masked, password / OTP / token fully redacted). Request-id binds to every
  log line via the `RequestIdMiddleware`.
- **Sentry** — DSN-driven init, no-op when absent. Release tag is
  `pharmacy-api@<version>+<git_sha>` (CI sets `GIT_SHA`).

## Security

- **Headers** (`SecurityHeadersMiddleware`): HSTS (HTTPS only), X-Frame-Options
  DENY, X-Content-Type-Options nosniff, Referrer-Policy strict-origin, CSP
  `default-src 'none'; frame-ancestors 'none'` (API serves JSON only).
- **Auth**: customer JWT (15-min access + 30-day refresh with jti rotation in
  Redis); admin email/password (argon2id) + server-side session in HttpOnly
  cookie. `get_current_user` and `get_current_admin` are SEPARATE dependencies
  (sacred invariant).
- **Rate limits**: per-phone OTP, per-IP burst, OTP verify, refresh token
  (BACKEND §20.5).
- **Audit log**: every admin mutation writes one `admin_audit_log` row in the
  same transaction. Tested by `test_admin_audit_coverage.py`.

## Deployment

- Dev: `docker-compose.yml` (mysql + redis + optional api/worker profile).
- Test: `docker-compose.yml` test profile (mysql-test on tmpfs, port 3307).
- Production: `docker-compose.production.yml` (Phase 12 — pinned tags,
  env-file driven, healthchecks).
- Worker: same image, different CMD (`arq app.workers.settings.WorkerSettings`).
- Backups: `bin/backup_db.sh` (mysqldump | gzip → R2 stub pending Q15).

## What's NOT here

- Frontend (separate project).
- Real production deploy + staging environment (separate effort with ops).
- Real Nikita / Freedom Pay / R2 adapter bodies (block on vendor docs —
  OPEN_QUESTIONS Q13/Q14/Q15).
- Multi-queue ARQ routing, gunicorn (Phase 1.5+).
- Email integration (Phase 12+).

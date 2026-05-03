# Deploy Runbook

> Production deploy via `docker-compose.production.yml`. Single-VPS topology
> per PHARMACY §22.2 (MVP). Multi-host / k8s is Phase 2.

## Prerequisites

- VPS with Docker + Docker Compose v2.
- DNS pointing `api.pharmacy.kg` → VPS IP, `cdn.pharmacy.kg` → R2 custom domain.
- TLS via Caddy or Cloudflare-proxied DNS (TLS terminates at the edge; the
  app runs on plain HTTP behind it).
- Secrets injected via `.env.production` (NOT committed). See
  `.env.example` for the shape.

## Required env vars

| Var | Source | Notes |
|---|---|---|
| `MYSQL_DSN` | vault | `mysql+asyncmy://user:pwd@host:3306/pharmacy` |
| `REDIS_DSN` | vault | `redis://host:6379/0` |
| `SECRET_KEY` | vault | 32+ bytes, JWT signing |
| `PASSWORD_PEPPER` | vault | 32+ bytes, argon2 pepper |
| `OTP_PEPPER` | vault | 32+ bytes, OTP HMAC pepper |
| `SENTRY_DSN` | sentry.io | optional; absent → no-op |
| `GIT_SHA` | CI | tag for Sentry release grouping |
| `METRICS_TOKEN` | vault | bearer for `/metrics`; absent → 401 |
| `SMS_PROVIDER` | env | `fake` (default — see Q13) |
| `PAYMENT_PROVIDER` | env | `fake` (default — see Q14) |
| `STORAGE_*` | env | absent → local-disk fake storage (Q15) |
| `CORS_ORIGINS` | env | comma-separated; storefront + admin domains |

> **Production blockers**: real-adapter env values for SMS / payments / storage
> are scaffolded but raise `NotImplementedError`. Set the providers to `fake`
> and capture in OPEN_QUESTIONS Q13/Q14/Q15 until vendor docs land.

## Deploy steps

1. **SSH into the VPS.**

   ```bash
   ssh deploy@api.pharmacy.kg
   cd /opt/pharmacy
   ```

2. **Pull the new image tag.**

   ```bash
   docker compose -f docker-compose.production.yml pull
   ```

3. **Apply migrations** (single command; idempotent if no new migrations).

   ```bash
   docker compose -f docker-compose.production.yml run --rm api \
     uv run alembic upgrade head
   ```

   On the very first deploy, this creates every table.

4. **Restart api + worker** (rolling: api first, then worker).

   ```bash
   docker compose -f docker-compose.production.yml up -d --no-deps api
   sleep 5
   curl -fsS https://api.pharmacy.kg/health/ready  # must return 200
   docker compose -f docker-compose.production.yml up -d --no-deps worker
   ```

5. **Verify** (each in turn):

   - `GET /health` → `{"status":"ok","version":"<new>"}`.
   - `GET /health/ready` → `{"status":"ok","db":"ok","redis":"ok",...}`.
   - `GET /metrics -H "Authorization: Bearer $METRICS_TOKEN"` → text exposition.
   - Admin login + place test order via the storefront.
   - Worker logs include `worker_startup` line + scheduled cron registrations.

## Rollback

See `rollback.md`.

## Smoke test (≤ 5 minutes)

```bash
# 1. Health
curl -fsS https://api.pharmacy.kg/health
curl -fsS https://api.pharmacy.kg/health/ready

# 2. Storefront browse
curl -fsS https://api.pharmacy.kg/api/v1/categories | jq '.items | length'
curl -fsS https://api.pharmacy.kg/api/v1/branches | jq '.[].id'

# 3. Search
curl -fsS "https://api.pharmacy.kg/api/v1/search?q=парацетамол" \
  -H "Accept-Language: ru" | jq '.total'

# 4. Admin login (manual through admin panel; verify session cookie)
```

## Common gotchas

- **Migrations failing on prod**: check `alembic_version` table; if it lists a
  revision newer than `migrations/versions/`, the image is stale — pull again.
- **/health/ready returns 503**: the body says which dep failed (`db` or
  `redis`). Check container connectivity to the managed services.
- **Worker logs no cron registrations**: the worker container booted with
  the wrong CMD; should be `arq app.workers.settings.WorkerSettings`.
- **Sentry release shows `+dev`**: CI didn't pass `GIT_SHA` to the image
  build; rebuild with `--build-arg GIT_SHA=$(git rev-parse HEAD)`.

# Pharmacy API

Backend for the Pharmacy Platform — Bishkek-launched OTC pharmacy e-commerce.

**Stack:** FastAPI · SQLAlchemy 2.x async · MySQL 8 · Redis · ARQ · Pydantic v2 · structlog.

> See `/specs` for the canonical product, data, and backend specifications.
> Read `CLAUDE.md` first if you're using an AI assistant in this repo.

---

## Prerequisites

- **Python 3.12** — uv will install and pin it automatically; your system Python is not touched.
- **Docker** with Docker Compose v2.
- **uv** — `brew install uv` (macOS) or `curl -LsSf https://astral.sh/uv/install.sh | sh`.

---

## Get to /health in 5 minutes

```bash
git clone <repo>
cd pharmacy_backend

uv sync                              # installs Python 3.12 + deps into .venv
cp .env.example .env                 # then edit JWT_SECRET and PASSWORD_PEPPER

make docker-up                       # MySQL :3306, Redis :6379
make dev                             # API on http://localhost:8000

curl http://localhost:8000/health
# → {"status":"ok","version":"0.1.0"}
```

`make help` lists every target.

---

## Quickstart with MAMP (local dev, no Docker)

If you already run MAMP (MySQL on :3306) on macOS and want to skip the
Docker stack:

```bash
# 1. Install + start Homebrew Redis (one-time).
brew install redis
brew services start redis
redis-cli ping                       # → PONG

# 2. Confirm MAMP MySQL has the pharmacy DB.
/Applications/MAMP/Library/bin/mysql80/bin/mysql -uroot -proot \
  -h127.0.0.1 -P3306 -e "CREATE DATABASE IF NOT EXISTS pharmacy
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"

# 3. Point .env at MAMP (the .env in the repo, generated locally).
#    Default DSN: mysql+asyncmy://root:root@localhost:3306/pharmacy
#    Default Redis: redis://localhost:6379/0

# 4. Apply migrations.
uv sync
set -a && source .env && set +a
uv run alembic upgrade head

# 5. Run the API.
make dev                             # http://localhost:8000
open http://localhost:8000/docs      # Swagger UI
```

### Logging in via Swagger UI

The customer API supports two parallel auth flows (additive — both
work):

* **Email + password (dev convenience)** —
  `POST /api/v1/auth/register` → `POST /api/v1/auth/login` →
  paste `Bearer <access_token>` into the Swagger "Authorize" dialog.
  Production deploys still use SMS-OTP per spec; this is a local-dev
  convenience added on top of v1.0.0-rc1 (see `DECISION_LOG.md`).

* **SMS-OTP (spec flow)** — `POST /api/v1/auth/otp/request` then
  `POST /api/v1/auth/otp/verify`. The default `SMS_PROVIDER=fake`
  logs the OTP code to the uvicorn output instead of sending a real
  SMS — copy the digits from the `sms_enqueued` log line.

---

## Daily commands

```bash
make test               # full test suite
make test-fast          # unit tests only
make lint               # ruff check + format check
make type               # mypy --strict
make fmt                # auto-fix lint + format
make worker             # ARQ worker (Phase 11+)
make shell-mysql        # MySQL CLI
make shell-redis        # Redis CLI
make pre-commit         # install + run hooks
```

---

## Layout

```
app/
  main.py               FastAPI app factory + lifespan
  worker.py             ARQ worker entrypoint
  core/                 cross-cutting infra (config, errors, logging, security, i18n, time)
  domain/<context>/     bounded contexts: identity, catalog, inventory, orders, payments, deliveries, ops
  api/v1/               customer API (prefix /api/v1)
  api/admin_v1/         admin API (prefix /api/admin/v1)
  workers/              ARQ jobs (Phase 11)
  integrations/         external service adapters: sms, payments, storage

migrations/             Alembic (Phase 2+)
tests/                  unit / integration / e2e
specs/                  blueprints — read-only during build phases
```

Full layout in `BACKEND_BLUEPRINT.md §3`.

---

## Where to look

| Question | File |
|---|---|
| What we're building (features, journeys, rules) | `specs/PRODUCT_BLUEPRINT.md` |
| Database schema and system design | `specs/PHARMACY_BLUEPRINT_2.md` |
| Implementation patterns (FastAPI / SQLAlchemy / MySQL) | `specs/BACKEND_BLUEPRINT.md` |
| Phased build prompts | `specs/CLAUDE_CODE_PROMPTS.md` |
| Project rules and invariants | `CLAUDE.md` |
| Current phase and what's next | `BUILD_PROGRESS.md` |
| Decisions made | `DECISION_LOG.md` |
| Open questions | `OPEN_QUESTIONS.md` |
| Active risks | `RISKS.md` |

---

## Conventions

- **Conventional Commits** (`feat(catalog): add product CRUD`).
- `make lint && make type && make test` clean before any PR.
- `BACKEND_BLUEPRINT.md §27` and `PRODUCT_BLUEPRINT.md §26` are gates — every phase walks both.
- Specs in `/specs` are read-only during build phases. Spec evolution = a deliberate human decision, never a silent edit.

---

## License

MIT.

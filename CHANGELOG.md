# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### Phase 0 (2026-05-02)
- Project initialised; specs and master plan in place.
- `BUILD_PLAN.md`, `BUILD_PROGRESS.md`, `OPEN_QUESTIONS.md` (12 substantive items), `RISKS.md` (top-10 ranked + watching list), `DECISION_LOG.md` template, this file.

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

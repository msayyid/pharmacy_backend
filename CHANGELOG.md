# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

#### Phase 0 (2026-05-02)
- Project initialised; specs and master plan in place.
- `BUILD_PLAN.md`, `BUILD_PROGRESS.md`, `OPEN_QUESTIONS.md` (12 substantive items), `RISKS.md` (top-10 ranked + watching list), `DECISION_LOG.md` template, this file.

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

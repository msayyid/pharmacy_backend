# Pharmacy Platform — Backend Blueprint

> **Purpose.** This is the canonical backend specification. It lives in `/specs` and is the source of truth for project structure, conventions, libraries, and patterns. Code generated for this project must conform to this document.
>
> **Companion docs.** This document references `PHARMACY_BLUEPRINT.md` for the database schema and overall system design. That document was originally written for PostgreSQL; **all schema specifics in this document override it for MySQL** (see §6).
>
> **Stack.** FastAPI (async) · SQLAlchemy 2.x async · MySQL 8.0+ · Alembic · Pydantic v2 · Redis · ARQ workers.

---

## Table of Contents

1. [Document Purpose & Rules for Claude Code](#1-document-purpose--rules-for-claude-code)
2. [Tech Stack & Pinned Versions](#2-tech-stack--pinned-versions)
3. [Directory Structure](#3-directory-structure)
4. [Naming Conventions](#4-naming-conventions)
5. [Configuration & Environments](#5-configuration--environments)
6. [MySQL Adaptation Guide (vs the PostgreSQL blueprint)](#6-mysql-adaptation-guide-vs-the-postgresql-blueprint)
7. [Database Layer](#7-database-layer)
8. [SQLAlchemy Models](#8-sqlalchemy-models)
9. [Alembic Migrations](#9-alembic-migrations)
10. [Pydantic Schemas](#10-pydantic-schemas)
11. [Repository Layer](#11-repository-layer)
12. [Service Layer](#12-service-layer)
13. [API Layer (Routers & Dependencies)](#13-api-layer-routers--dependencies)
14. [Authentication & Authorization](#14-authentication--authorization)
15. [Validation, Errors & Exception Handling](#15-validation-errors--exception-handling)
16. [Middleware & Cross-cutting Concerns](#16-middleware--cross-cutting-concerns)
17. [Background Jobs (ARQ)](#17-background-jobs-arq)
18. [Caching (Redis)](#18-caching-redis)
19. [Logging](#19-logging)
20. [Pagination, Filtering, Sorting](#20-pagination-filtering-sorting)
21. [Idempotency](#21-idempotency)
22. [Internationalization](#22-internationalization)
23. [Testing](#23-testing)
24. [Code Quality (lint, type-check, format)](#24-code-quality-lint-type-check-format)
25. [Local Development (docker-compose)](#25-local-development-docker-compose)
26. [Vertical Slice — End-to-End Example](#26-vertical-slice--end-to-end-example)
27. [Conventions Checklist for Claude Code](#27-conventions-checklist-for-claude-code)

---

## 1. Document Purpose & Rules for Claude Code

This file is loaded by Claude Code as project context. When generating or modifying code:

1. **Do not invent libraries or patterns.** If something is not specified here, ask before introducing it.
2. **Match the directory structure exactly.** New files go in the layer they belong to (router / service / repository / model / schema).
3. **Async everywhere.** Every database call uses `AsyncSession`. Every IO-bound operation is `async`. No mixing sync DB calls inside async handlers.
4. **No raw SQL in routers or services.** Raw SQL belongs in repositories, behind a method.
5. **No business logic in routers.** Routers parse input, call a service, shape the response. Nothing else.
6. **No ORM models in API responses.** Always go through Pydantic response schemas.
7. **No `print()` and no bare `logging.getLogger(__name__)` calls in business code.** Use `app.core.logging.get_logger(__name__)`.
8. **Type-hint everything.** `mypy --strict` must pass.
9. **Write tests with the code, not after.** Every router gets at least one happy-path and one auth/validation test.
10. **Follow the conventions checklist in §27 before declaring a task done.**

---

## 2. Tech Stack & Pinned Versions

Pin majors; floats inside the major are fine.

```toml
# pyproject.toml — runtime dependencies
[project]
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115,<0.116",
    "uvicorn[standard]>=0.32,<0.33",
    "gunicorn>=23.0,<24.0",
    "sqlalchemy[asyncio]>=2.0.36,<2.1",
    "asyncmy>=0.2.10,<0.3",                # async MySQL driver
    "alembic>=1.14,<1.15",
    "pydantic>=2.9,<3.0",
    "pydantic-settings>=2.6,<3.0",
    "python-jose[cryptography]>=3.3,<4.0", # JWT
    "passlib[argon2]>=1.7.4,<2.0",
    "argon2-cffi>=23.1,<24.0",
    "redis>=5.2,<6.0",
    "arq>=0.26,<0.27",                     # async background jobs
    "httpx>=0.27,<0.28",                   # outbound HTTP
    "python-multipart>=0.0.18,<0.1",       # form/file uploads
    "structlog>=24.4,<25.0",
    "orjson>=3.10,<4.0",
    "tenacity>=9.0,<10.0",                 # retries
    "phonenumbers>=8.13,<9.0",
    "boto3>=1.35,<2.0",                    # R2/S3
    "pillow>=11.0,<12.0",                  # image processing in worker
    "sentry-sdk[fastapi]>=2.18,<3.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3,<9.0",
    "pytest-asyncio>=0.24,<0.25",
    "pytest-cov>=6.0,<7.0",
    "httpx>=0.27,<0.28",
    "asgi-lifespan>=2.1,<3.0",
    "factory-boy>=3.3,<4.0",
    "freezegun>=1.5,<2.0",
    "ruff>=0.8,<0.9",
    "mypy>=1.13,<2.0",
    "types-passlib",
    "pre-commit>=4.0,<5.0",
]
```

**Why these choices:**

| Choice | Reason |
|---|---|
| Python 3.12 | Stable, fast, good async story, supported by all libs above |
| `asyncmy` | Maintained async MySQL driver; faster than `aiomysql` and supports MySQL 8 features |
| SQLAlchemy 2.x async | Modern async API, `Mapped[]` type-hinted models, integrates with mypy |
| Pydantic v2 | 5–50× faster than v1, better type inference |
| ARQ over Celery | Async-native, simpler ops; Celery is overkill for MVP and pulls a sync worker stack |
| structlog | Structured JSON logs out of the box; integrates with stdlib logging |
| argon2 | Modern password hashing (use `argon2id`) |
| orjson | Faster JSON serialisation; FastAPI can use it as default response class |

---

## 3. Directory Structure

```
pharmacy-backend/
├── pyproject.toml
├── uv.lock                         # or poetry.lock
├── README.md
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── docker-compose.yml              # local dev: app, mysql, redis
├── Dockerfile
├── alembic.ini
├── specs/                          # blueprints (this folder)
│   ├── PHARMACY_BLUEPRINT.md
│   └── BACKEND_BLUEPRINT.md
│
├── migrations/                     # alembic
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── tests/
│   ├── conftest.py
│   ├── factories/
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
└── app/
    ├── __init__.py
    ├── main.py                     # FastAPI app factory + lifespan
    ├── worker.py                   # ARQ worker entrypoint
    │
    ├── core/                       # cross-cutting infrastructure
    │   ├── __init__.py
    │   ├── config.py               # Settings (pydantic-settings)
    │   ├── db.py                   # engine, session, get_db
    │   ├── redis.py                # redis client
    │   ├── security.py             # password hashing, JWT, OTP hashing
    │   ├── logging.py              # structlog config + get_logger
    │   ├── errors.py               # AppError hierarchy
    │   ├── pagination.py           # cursor + offset helpers
    │   ├── i18n.py                 # language resolution
    │   ├── types.py                # custom SQLAlchemy types (GUID, etc.)
    │   └── time.py                 # utcnow(), bishkek_now()
    │
    ├── domain/                     # bounded contexts
    │   ├── __init__.py
    │   │
    │   ├── identity/               # users, otp, admins, sessions
    │   │   ├── __init__.py
    │   │   ├── models.py
    │   │   ├── schemas.py
    │   │   ├── repositories.py
    │   │   ├── services.py
    │   │   ├── dependencies.py     # get_current_user, require_role
    │   │   └── jobs.py             # background jobs related to identity
    │   │
    │   ├── catalog/                # categories, products, ingredients, symptoms
    │   ├── inventory/              # branches, branch_products, batches, movements
    │   ├── orders/                 # carts, orders, order_items, status history
    │   ├── payments/               # payments
    │   ├── deliveries/             # deliveries
    │   └── ops/                    # audit log, sms log, search log
    │
    ├── api/                        # HTTP layer (FastAPI routers)
    │   ├── __init__.py
    │   ├── deps.py                 # shared dependencies
    │   ├── errors.py               # exception handlers
    │   ├── middleware.py           # request id, timing, etc.
    │   │
    │   ├── v1/
    │   │   ├── __init__.py
    │   │   ├── router.py           # APIRouter(prefix="/api/v1")
    │   │   ├── auth.py
    │   │   ├── account.py
    │   │   ├── catalog.py
    │   │   ├── search.py
    │   │   ├── cart.py
    │   │   ├── checkout.py
    │   │   ├── orders.py
    │   │   └── content.py
    │   │
    │   └── admin_v1/
    │       ├── __init__.py
    │       ├── router.py           # APIRouter(prefix="/api/admin/v1")
    │       ├── auth.py
    │       ├── products.py
    │       ├── inventory.py
    │       ├── orders.py
    │       ├── reports.py
    │       ├── users.py
    │       ├── team.py
    │       └── audit.py
    │
    ├── workers/                    # ARQ jobs (registry + impls)
    │   ├── __init__.py
    │   ├── settings.py             # WorkerSettings
    │   ├── sms.py
    │   ├── images.py
    │   ├── imports.py
    │   ├── reports.py
    │   └── scheduled.py            # cron-like jobs (near_expiry, etc.)
    │
    └── integrations/               # external service clients
        ├── __init__.py
        ├── sms/                    # Nikita / Megacom adapters
        │   ├── __init__.py
        │   ├── base.py             # SmsClient protocol
        │   ├── nikita.py
        │   └── fake.py             # for tests
        ├── payments/               # FreedomPay, MBank
        │   ├── base.py
        │   ├── freedom_pay.py
        │   └── fake.py
        └── storage/                # S3/R2
            ├── base.py
            └── r2.py
```

**Why this layout:**

- `domain/` is split by **bounded context**, not by technical layer. All code for "orders" sits together — a developer touching orders rarely opens five distant folders.
- `api/` is the only layer that knows about HTTP. Domain code is testable without spinning up FastAPI.
- `core/` is small on purpose; it holds infrastructure that every domain uses.
- `integrations/` wraps third parties behind protocols so we can swap or fake them.
- `workers/` re-uses `domain/` services. Jobs are thin shells.

**Anti-patterns to avoid:**

- ❌ A flat `app/models.py` with every table
- ❌ A `utils/` folder that grows into a junk drawer
- ❌ Domain code that imports from `api/`
- ❌ `crud.py` files containing business logic

---

## 4. Naming Conventions

| Thing | Convention | Example |
|---|---|---|
| Module | `snake_case` | `order_repository.py` |
| Class | `PascalCase` | `OrderRepository`, `PlaceOrderService` |
| Function / method | `snake_case` | `place_order` |
| Constant | `UPPER_SNAKE_CASE` | `OTP_TTL_SECONDS` |
| Pydantic schema | `<Name>Read`, `<Name>Create`, `<Name>Update`, `<Name>InDB` | `ProductRead` |
| SQLAlchemy model | singular noun | `Product`, `OrderItem` |
| DB table | plural snake_case | `products`, `order_items` |
| Repository | `<Aggregate>Repository` | `ProductRepository` |
| Service | `<Verb><Noun>Service` or `<Domain>Service` | `PlaceOrderService`, `CatalogService` |
| Router var | `router` | `router = APIRouter(...)` |
| Dependency | `get_*` or `require_*` | `get_current_user`, `require_role(...)` |
| Async test | `async def test_*` | `async def test_place_order_happy_path` |
| Custom exception | `<Subject>Error` | `OutOfStockError`, `InvalidOTPError` |
| Background job | `<verb>_<object>` | `send_sms`, `process_image_upload` |

**Avoid:** `manager`, `helper`, `util`, `handler` — they hide what the code actually does.

---

## 5. Configuration & Environments

### 5.1 Settings module

```python
# app/core/config.py
from functools import lru_cache
from typing import Literal
from pydantic import Field, MySQLDsn, RedisDsn, AnyHttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    # ─── App
    env: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False
    app_name: str = "pharmacy-api"
    api_v1_prefix: str = "/api/v1"
    admin_v1_prefix: str = "/api/admin/v1"
    base_url: AnyHttpUrl = Field(default="http://localhost:8000")

    # ─── Security
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 30
    password_pepper: SecretStr                  # extra static secret for argon2
    admin_session_ttl_hours: int = 12

    # ─── DB
    mysql_dsn: MySQLDsn                         # mysql+asyncmy://user:pass@host:3306/db
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800         # avoid MySQL "server has gone away"
    db_echo: bool = False

    # ─── Redis
    redis_dsn: RedisDsn

    # ─── i18n
    default_language: Literal["ru", "ky", "en"] = "ru"
    supported_languages: tuple[str, ...] = ("ru", "ky", "en")

    # ─── OTP
    otp_length: int = 6
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5

    # ─── Rate limits (per-window counters in Redis)
    rl_otp_request_per_phone_window_seconds: int = 900   # 15 min
    rl_otp_request_per_phone_max: int = 3

    # ─── External services
    sms_provider: Literal["nikita", "fake"] = "fake"
    sms_api_url: AnyHttpUrl | None = None
    sms_api_key: SecretStr | None = None
    sms_sender: str = "Pharmacy"

    payment_provider: Literal["freedom_pay", "fake"] = "fake"
    payment_api_url: AnyHttpUrl | None = None
    payment_merchant_id: str | None = None
    payment_secret: SecretStr | None = None

    storage_endpoint: AnyHttpUrl | None = None  # R2 endpoint
    storage_bucket: str | None = None
    storage_access_key: SecretStr | None = None
    storage_secret_key: SecretStr | None = None
    storage_public_base_url: AnyHttpUrl | None = None

    sentry_dsn: SecretStr | None = None

    # ─── CORS
    cors_origins: list[AnyHttpUrl] = []


@lru_cache
def get_settings() -> Settings:
    return Settings()  # reads env / .env
```

**Rules:**

- Settings are **read once** at app start via `lru_cache`. Do not call `Settings()` directly in code.
- Inject settings as a dependency: `settings: Annotated[Settings, Depends(get_settings)]`.
- Secrets are `SecretStr`. Never `print(settings)` — use `settings.model_dump(exclude={"jwt_secret", "password_pepper", ...})`.
- `.env.example` lists every variable with a placeholder and a comment.

### 5.2 Environment files

| File | Used in | Committed |
|---|---|---|
| `.env.example` | reference | yes |
| `.env` | local dev | no (gitignored) |
| `.env.test` | tests | yes (no real secrets) |
| Production env | env vars in deploy target | n/a |

---

## 6. MySQL Adaptation Guide (vs the PostgreSQL blueprint)

The schema in `PHARMACY_BLUEPRINT.md` was Postgres-flavoured. Apply these adjustments throughout when generating models and migrations.

### 6.1 Server settings (must be set on the MySQL instance)

```sql
-- Server config
character_set_server = utf8mb4
collation_server     = utf8mb4_0900_ai_ci   -- accent + case insensitive, MySQL 8 default
default_storage_engine = InnoDB
sql_mode = STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO
innodb_default_row_format = DYNAMIC
time_zone = '+00:00'
```

> Application stores everything in UTC; `Asia/Bishkek` is applied at presentation time.

### 6.2 Type mappings

| PostgreSQL | MySQL 8 / SQLAlchemy | Notes |
|---|---|---|
| `UUID` (`gen_random_uuid()`) | `BINARY(16)` via custom `GUID` type | Generated app-side with `uuid7` for index-friendly ordering |
| `BIGSERIAL` | `BIGINT AUTO_INCREMENT` | Same shape via `Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)` |
| `TIMESTAMPTZ` | `DATETIME(6)` (UTC) | MySQL has no timezone-aware type; we standardise on UTC at the app layer |
| `TEXT` | `TEXT` | Use `MEDIUMTEXT` if > 64 KB expected (descriptions OK as TEXT) |
| `JSONB` | `JSON` | MySQL 8's `JSON` is fine; index via generated columns |
| `CITEXT` | `VARCHAR(n) COLLATE utf8mb4_0900_ai_ci` | The collation provides case-insensitive comparisons |
| `INET` | `VARBINARY(16)` | Or just `VARCHAR(45)` for human-readable IPv4/v6 |
| `ENUM` (Postgres) | Python `enum.Enum` mapped to `VARCHAR(32)` + `CHECK` | Avoid MySQL's native `ENUM` — `ALTER TABLE` is painful |
| `tsvector` + GIN | `FULLTEXT INDEX` (InnoDB, `WITH PARSER ngram`) | Different query syntax (`MATCH ... AGAINST`) |
| `pg_trgm` similarity | None native | Use FULLTEXT for fuzzy; consider Meilisearch earlier |
| `unaccent` | Collation handles accent-insensitivity | `utf8mb4_0900_ai_ci` is "accent insensitive" |

### 6.3 Constructs to replace

| Postgres feature | MySQL alternative |
|---|---|
| Partial indexes (`WHERE col IS NULL`) | Not supported. Use functional indexes on generated columns, or full index. |
| Partial unique (e.g. one default address) | Generated column trick: `is_default_user_id BIGINT GENERATED ALWAYS AS (IF(is_default, user_id, NULL))` + `UNIQUE(is_default_user_id)` |
| `INSERT ... ON CONFLICT` | `INSERT ... ON DUPLICATE KEY UPDATE` |
| `RETURNING` | Not available in plain `INSERT`; SQLAlchemy uses a `SELECT` after insert when needed |
| `CREATE EXTENSION` | n/a |
| `gen_random_uuid()` | App-side `uuid.uuid7()` (Python `uuid7` package) → `BINARY(16)` |
| `tsvector` generated column | `FULLTEXT(name, description)` index with `WITH PARSER ngram` |
| `FOR UPDATE SKIP LOCKED` | ✅ Supported in MySQL 8.0+ |
| `CHECK` constraints | ✅ Enforced from MySQL 8.0.16+ |
| Recursive CTE | ✅ Supported |

### 6.4 Full-text search (Cyrillic)

```sql
-- on product_translations
ALTER TABLE product_translations
  ADD FULLTEXT INDEX ftx_pt_search (name, short_description, description)
  WITH PARSER ngram;
```

Query:
```sql
SELECT id, MATCH(name, short_description, description)
            AGAINST ('+парацетамол' IN BOOLEAN MODE) AS score
FROM product_translations
WHERE language_code = 'ru'
  AND MATCH(name, short_description, description)
       AGAINST ('+парацетамол' IN BOOLEAN MODE)
ORDER BY score DESC
LIMIT 50;
```

The ngram parser tokenises Cyrillic into character n-grams, giving substring matching for free. Default `ngram_token_size = 2`; consider `ngram_token_size = 3` for fewer false positives at the cost of recall.

> ⚠️ **Migration plan from §10 of the PG blueprint:** Postgres FTS + trigram is replaced by MySQL FULLTEXT + ngram. Move to Meilisearch sooner than the PG plan suggested — at the first whiff of search latency or quality complaints.

### 6.5 "Partial unique" patterns we still need

**One default address per user:**

```python
class UserAddress(Base):
    __tablename__ = "user_addresses"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[bytes] = mapped_column(GUID, ForeignKey("users.id"))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # generated column: equals user_id when is_default=True, NULL otherwise
    default_user_id: Mapped[bytes | None] = mapped_column(
        BINARY(16),
        Computed("IF(is_default, user_id, NULL)", persisted=True),
    )
    __table_args__ = (
        UniqueConstraint("default_user_id", name="uq_user_addresses_default_user"),
    )
```

The same trick applies to "one primary image per product".

### 6.6 Datetime defaults

Postgres' `DEFAULT NOW()` becomes:

```python
created_at: Mapped[datetime] = mapped_column(
    DateTime(6), nullable=False,
    server_default=func.utc_timestamp(6),
)
updated_at: Mapped[datetime] = mapped_column(
    DateTime(6), nullable=False,
    server_default=func.utc_timestamp(6),
    onupdate=func.utc_timestamp(6),
)
```

Always store in **UTC**. Never use MySQL `CURRENT_TIMESTAMP` — it's affected by `time_zone` session var.

---

## 7. Database Layer

### 7.1 Engine and session

```python
# app/core/db.py
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)
from app.core.config import get_settings

settings = get_settings()

engine: AsyncEngine = create_async_engine(
    str(settings.mysql_dsn),
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle_seconds,
    pool_pre_ping=True,                # detects stale connections
    future=True,
    connect_args={"charset": "utf8mb4"},
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. One session per request, commit/rollback on exit."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """For workers and scripts (no FastAPI request)."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### 7.2 Custom GUID type

```python
# app/core/types.py
import uuid
from sqlalchemy.types import TypeDecorator, BINARY


class GUID(TypeDecorator):
    """UUID stored as BINARY(16) with optimised byte order for MySQL B-tree.
    Accepts uuid.UUID or 36-char string; returns uuid.UUID."""
    impl = BINARY(16)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            value = uuid.UUID(value)
        # swap fields for time-ordered prefix (mirrors MySQL UUID_TO_BIN(_, 1))
        b = value.bytes
        return b[6:8] + b[4:6] + b[0:4] + b[8:]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        b = value
        original = b[4:8] + b[2:4] + b[0:2] + b[8:]
        return uuid.UUID(bytes=original)
```

UUIDs are generated app-side with `uuid7()` (time-ordered) — pass them in explicitly rather than relying on a DB default:

```python
from uuid_extensions import uuid7         # or any uuid7 lib

new_id = uuid7()
```

### 7.3 Base, mixins

```python
# app/core/db_base.py
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Project ORM base. All models inherit this."""
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(6), nullable=False,
        server_default=func.utc_timestamp(6),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), nullable=False,
        server_default=func.utc_timestamp(6),
        onupdate=func.utc_timestamp(6),
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(6))
```

### 7.4 Session rules

1. **One session per request.** Routers depend on `get_db`. Services and repositories receive the session as a constructor argument.
2. **Repositories never commit.** Only the request boundary commits (via `get_db`). Services may call `session.flush()` to surface integrity errors mid-transaction.
3. **No nested sessions.** If you need a sub-transaction, use `async with session.begin_nested():` (savepoint).
4. **Workers manage their own sessions** via `session_scope()` — one session per job execution.
5. **Long-running operations (imports)** must batch and `flush()` periodically, not hold a single transaction over thousands of rows.
6. **Reads outside a request** (rare) use `session_scope()` and rely on auto-rollback.

### 7.5 Connection pool guidance

| Setting | Value | Why |
|---|---|---|
| `pool_size` | 10 | Per-process baseline |
| `max_overflow` | 20 | Burst capacity |
| `pool_recycle` | 1800 | MySQL `wait_timeout` is 28800 by default; recycle well before |
| `pool_pre_ping` | True | Avoids "MySQL server has gone away" after idle |

Total connections to MySQL = `(pool_size + max_overflow) × num_app_processes × num_app_replicas`. Keep MySQL `max_connections` comfortably above this.


---

## 8. SQLAlchemy Models

### 8.1 Conventions

1. **One file per bounded context** — `app/domain/<context>/models.py`. Don't shard models across many files inside a single context.
2. **Use `Mapped[...]` typing** — required for SQLAlchemy 2.x and mypy support.
3. **Declare relationships with `relationship(..., lazy="raise")`** by default — forces explicit loading at query time, no surprise N+1.
4. **Foreign keys always have `ondelete=` explicit.**
5. **`__table_args__` lists indexes, unique constraints, check constraints in that order.**
6. **Index naming**: `idx_<table>_<columns>`, unique: `uq_<table>_<columns>`, check: `chk_<table>_<rule>`, FK: `fk_<table>_<ref>`.
7. **Money is `Numeric(12, 2)`** — never `Float`.
8. **Use Python `enum.Enum` mapped to `String(32)` + `CHECK`**, not MySQL native ENUM.

### 8.2 Reference model — `Product`

```python
# app/domain/catalog/models.py
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index,
    Integer, JSON, Numeric, SmallInteger, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_base import Base, TimestampMixin, SoftDeleteMixin
from app.core.types import GUID


class ProductForm(StrEnum):
    TABLET = "tablet"
    CAPSULE = "capsule"
    SYRUP = "syrup"
    DROPS = "drops"
    CREAM = "cream"
    OINTMENT = "ointment"
    GEL = "gel"
    SPRAY = "spray"
    INHALER = "inhaler"
    INJECTION = "injection"
    SUPPOSITORY = "suppository"
    PATCH = "patch"
    POWDER = "powder"
    SOLUTION = "solution"
    SUSPENSION = "suspension"
    LOZENGE = "lozenge"
    OTHER = "other"


class Product(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "products"

    id: Mapped[UUID] = mapped_column(GUID, primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(40))
    slug: Mapped[str] = mapped_column(String(160), nullable=False)

    manufacturer_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("manufacturers.id", name="fk_products_manufacturer", ondelete="RESTRICT"),
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("categories.id", name="fk_products_category", ondelete="RESTRICT"),
        nullable=False,
    )

    form: Mapped[ProductForm] = mapped_column(
        String(32), nullable=False, default=ProductForm.OTHER,
    )
    pack_size_label: Mapped[str | None] = mapped_column(String(60))
    pack_quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    pack_unit: Mapped[str | None] = mapped_column(String(16))

    requires_prescription: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_age: Mapped[int | None] = mapped_column(SmallInteger)
    max_per_order: Mapped[int | None] = mapped_column(SmallInteger)

    storage_temp_min_c: Mapped[int | None] = mapped_column(SmallInteger)
    storage_temp_max_c: Mapped[int | None] = mapped_column(SmallInteger)
    requires_cold_chain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weight_grams: Mapped[int | None] = mapped_column(Integer)

    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships (always lazy="raise" — explicit loading required)
    translations: Mapped[list["ProductTranslation"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="raise",
    )
    images: Mapped[list["ProductImage"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("sku", name="uq_products_sku"),
        UniqueConstraint("slug", name="uq_products_slug"),
        Index("idx_products_barcode", "barcode"),
        Index("idx_products_category_active", "category_id", "is_active"),
        Index("idx_products_manufacturer", "manufacturer_id"),
        Index("idx_products_featured", "is_featured", "created_at"),
        Index("idx_products_created_at", "created_at"),
        CheckConstraint(
            "form IN ('tablet','capsule','syrup','drops','cream','ointment','gel',"
            "'spray','inhaler','injection','suppository','patch','powder',"
            "'solution','suspension','lozenge','other')",
            name="chk_products_form",
        ),
        CheckConstraint(
            "storage_temp_min_c IS NULL OR storage_temp_max_c IS NULL "
            "OR storage_temp_min_c <= storage_temp_max_c",
            name="chk_products_temp_range",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4",
         "mysql_collate": "utf8mb4_0900_ai_ci"},
    )
```

### 8.3 Translation model with FULLTEXT

```python
class ProductTranslation(Base):
    __tablename__ = "product_translations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[UUID] = mapped_column(
        GUID,
        ForeignKey("products.id", name="fk_pt_product", ondelete="CASCADE"),
        nullable=False,
    )
    language_code: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_description: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(String(8000))
    usage_instructions: Mapped[str | None] = mapped_column(String(8000))
    side_effects: Mapped[str | None] = mapped_column(String(8000))
    contraindications: Mapped[str | None] = mapped_column(String(8000))
    composition: Mapped[str | None] = mapped_column(String(2000))

    product: Mapped[Product] = relationship(back_populates="translations", lazy="raise")

    __table_args__ = (
        UniqueConstraint("product_id", "language_code", name="uq_pt_product_lang"),
        Index("idx_pt_lang_name", "language_code", "name"),
        # FULLTEXT index — created in migration with mysql_prefix
        Index(
            "ftx_pt_search",
            "name", "short_description", "description",
            mysql_prefix="FULLTEXT",
        ),
        CheckConstraint(
            "language_code IN ('ru','ky','en')",
            name="chk_pt_language",
        ),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4",
         "mysql_collate": "utf8mb4_0900_ai_ci"},
    )
```

> The `mysql_prefix="FULLTEXT"` tells SQLAlchemy to emit `CREATE FULLTEXT INDEX`. The `WITH PARSER ngram` clause is added in the Alembic migration (see §9.4) since SQLAlchemy doesn't expose it directly.

### 8.4 Loading strategies

Default `lazy="raise"` forces explicit load decisions:

```python
# Eager-load when the caller knows it needs them
stmt = (
    select(Product)
    .options(
        selectinload(Product.translations),
        selectinload(Product.images),
    )
    .where(Product.id == product_id)
)
```

| Strategy | When |
|---|---|
| `selectinload` | One-to-many that fits in one IN-query (default for collections) |
| `joinedload` | Many-to-one or one-to-one when you need scalar inclusion |
| `raiseload` | Belt-and-braces when you want to assert no lazy load happens |
| `noload` | Never load this relationship at all |
| `lazyload` | Only when the call path *actually* benefits — usually it doesn't |

**Rule:** Never trigger a lazy load inside an async response serialisation. If `expire_on_commit=False` and the object is detached, lazy access will explode with `MissingGreenlet`.

---

## 9. Alembic Migrations

### 9.1 Setup

```ini
# alembic.ini (key parts)
[alembic]
script_location = migrations
file_template = %%(year)d%%(month).2d%%(day).2d_%%(hour).2d%%(minute).2d_%%(slug)s
sqlalchemy.url =                       ; resolved at runtime in env.py
```

```python
# migrations/env.py — async-friendly
import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

from app.core.config import get_settings
from app.core.db_base import Base
# IMPORTANT: import all models so they're registered on Base.metadata
import app.domain.identity.models      # noqa: F401
import app.domain.catalog.models       # noqa: F401
import app.domain.inventory.models     # noqa: F401
import app.domain.orders.models        # noqa: F401
import app.domain.payments.models      # noqa: F401
import app.domain.deliveries.models    # noqa: F401
import app.domain.ops.models           # noqa: F401

settings = get_settings()

config = context.config
config.set_main_option("sqlalchemy.url", str(settings.mysql_dsn))
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(settings.mysql_dsn),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=False,             # not needed for MySQL
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

### 9.2 Workflow

```bash
# Create a migration from model changes
alembic revision --autogenerate -m "add product attributes column"

# Review the generated file. Always.
# Apply
alembic upgrade head

# Roll back one
alembic downgrade -1
```

### 9.3 Autogenerate caveats (MySQL-specific)

Always inspect the generated SQL for these:

- **Column type widening** (e.g. `VARCHAR(80)` → `VARCHAR(160)`) is autogenerated correctly — but watch row size on wide tables.
- **`CHECK` constraints on enums** — Alembic may not detect changes to allowed values; edit by hand.
- **FULLTEXT indexes** — Alembic can create them but the `WITH PARSER ngram` modifier requires a manual `op.execute(...)` line. See §9.4.
- **Default value differences** — MySQL doesn't store `func.utc_timestamp(6)` literally; alembic may produce noisy diffs. Use `compare_server_default=True` and accept some manual cleanup.
- **Charset / collation drift** — every CREATE TABLE op must include `mysql_charset` / `mysql_collate` to prevent default `latin1` sneaking in on non-default servers.

### 9.4 FULLTEXT index migration template

```python
# in a migration file
def upgrade() -> None:
    op.execute("""
        CREATE FULLTEXT INDEX ftx_pt_search
        ON product_translations (name, short_description, description)
        WITH PARSER ngram
    """)


def downgrade() -> None:
    op.execute("DROP INDEX ftx_pt_search ON product_translations")
```

### 9.5 Migration content rules

- **One logical change per migration.** Schema change OR data change, not both, unless they're coupled.
- **No destructive autogenerate without review.** A `DROP COLUMN` line should never reach `main` without explicit confirmation.
- **Backfills are separate migrations** with explicit batch sizes — never `UPDATE x SET y = ...` over millions of rows in one transaction.
- **Never `data_migration_in_alembic` for slow operations.** Use a one-off management script that workers can resume.

---

## 10. Pydantic Schemas

### 10.1 Three-layer separation

For each resource, define schemas in `app/domain/<context>/schemas.py`:

| Suffix | Purpose | Example |
|---|---|---|
| `<Name>Create` | request body for POST | `ProductCreate` |
| `<Name>Update` | request body for PATCH (all fields optional) | `ProductUpdate` |
| `<Name>Read` | response body for GET / list items | `ProductRead` |
| `<Name>Detail` | response body when full detail differs from list shape | `ProductDetail` |
| `<Name>InternalSnapshot` | denormalised data captured at order time | `OrderItemSnapshot` |

> **Never** return ORM models from a router. Always pass through a `Read` / `Detail` schema.

### 10.2 Example

```python
# app/domain/catalog/schemas.py
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductBase(BaseModel):
    sku: Annotated[str, Field(min_length=1, max_length=40)]
    barcode: Annotated[str | None, Field(max_length=40)] = None
    slug: Annotated[str, Field(min_length=1, max_length=160, pattern=r"^[a-z0-9-]+$")]
    category_id: int
    manufacturer_id: int | None = None
    form: str = "other"
    pack_size_label: Annotated[str | None, Field(max_length=60)] = None
    requires_prescription: bool = False
    min_age: int | None = Field(default=None, ge=0, le=120)
    max_per_order: int | None = Field(default=None, gt=0)
    is_active: bool = True
    is_featured: bool = False


class ProductCreate(ProductBase):
    """Used for POST /admin/products."""
    pass


class ProductUpdate(BaseModel):
    """All optional. PATCH semantics."""
    model_config = ConfigDict(extra="forbid")
    barcode: str | None = None
    category_id: int | None = None
    manufacturer_id: int | None = None
    is_active: bool | None = None
    is_featured: bool | None = None
    # ... rest


class ProductTranslationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    language_code: str
    name: str
    short_description: str | None
    description: str | None


class ProductImageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    thumbnail_url: str | None
    medium_url: str | None
    large_url: str | None
    alt_text: str | None
    is_primary: bool


class ProductRead(BaseModel):
    """List item shape."""
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sku: str
    slug: str
    name: str                    # resolved from translations at service layer
    short_description: str | None
    price: Decimal
    currency: str
    available: int
    primary_image_url: str | None


class ProductDetail(ProductRead):
    """Detail view."""
    description: str | None
    usage_instructions: str | None
    side_effects: str | None
    contraindications: str | None
    images: list[ProductImageRead]
    manufacturer: str | None
    pack_size_label: str | None
    requires_prescription: bool
```

### 10.3 Conventions

- `model_config = ConfigDict(from_attributes=True)` on every Read schema (replaces v1 `orm_mode`).
- `model_config = ConfigDict(extra="forbid")` on every Create/Update schema — reject typos in field names.
- Validate at the schema layer (length, pattern, min/max) — don't repeat in services.
- Domain validation that needs DB lookups (e.g. "category exists") happens in the service layer.
- `Annotated[type, Field(...)]` instead of `field: type = Field(...)` — reads better and composes.
- For phones, use a custom validator that runs `phonenumbers.parse()` and stores E.164.

```python
from phonenumbers import NumberParseException, parse, is_valid_number, format_number, PhoneNumberFormat

def normalise_phone(v: str) -> str:
    try:
        n = parse(v, "KG")
    except NumberParseException as e:
        raise ValueError("invalid phone") from e
    if not is_valid_number(n):
        raise ValueError("invalid phone")
    return format_number(n, PhoneNumberFormat.E164)


class OtpRequestIn(BaseModel):
    phone: str
    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalise_phone(v)
```

### 10.4 Pagination & list envelopes

Every list endpoint returns the same envelope:

```python
# app/core/pagination.py
from typing import Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")

class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int | None = None        # offset paging
    page: int | None = None
    page_size: int | None = None

class Cursor(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
```

---

## 11. Repository Layer

### 11.1 Responsibilities

A repository is a thin layer over a single **aggregate root**. It:

- Owns the queries for that aggregate
- Returns ORM models (or `None`)
- Never commits, never opens a session
- Never knows about HTTP, Pydantic, or external services

### 11.2 Pattern

```python
# app/domain/catalog/repositories.py
from collections.abc import Sequence
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.catalog.models import Product, ProductTranslation


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, product_id: UUID) -> Product | None:
        stmt = select(Product).where(Product.id == product_id, Product.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_slug_with_translations(
        self, slug: str, lang: str,
    ) -> Product | None:
        stmt = (
            select(Product)
            .options(selectinload(Product.translations), selectinload(Product.images))
            .where(Product.slug == slug, Product.deleted_at.is_(None))
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_category(
        self,
        category_id: int,
        lang: str,
        offset: int,
        limit: int,
    ) -> tuple[Sequence[Product], int]:
        base = (
            select(Product)
            .where(
                Product.category_id == category_id,
                Product.is_active.is_(True),
                Product.deleted_at.is_(None),
            )
        )
        total_stmt = select(func.count()).select_from(base.subquery())
        items_stmt = (
            base.options(selectinload(Product.translations), selectinload(Product.images))
            .order_by(Product.is_featured.desc(), Product.created_at.desc())
            .offset(offset).limit(limit)
        )
        total = (await self.session.execute(total_stmt)).scalar_one()
        items = (await self.session.execute(items_stmt)).scalars().all()
        return items, total

    async def add(self, product: Product) -> None:
        self.session.add(product)
        await self.session.flush()        # surfaces UNIQUE / CHECK violations now

    async def soft_delete(self, product: Product) -> None:
        product.deleted_at = func.utc_timestamp(6)
        await self.session.flush()
```

### 11.3 Rules

- One repository class per aggregate.
- Methods are CRUD-shaped and named for **intent**, not SQL: `get_by_slug_with_translations`, not `select_with_join`.
- Returns ORM models or scalars. **Never** Pydantic schemas.
- No `session.commit()` inside.
- No business rules. "Can this product be deleted?" lives in the service.
- If a query is used by exactly one service method, it still goes in the repository.

### 11.4 Anti-patterns

- ❌ `def __init__(self): self.session = SessionLocal()` — repository creating its own session
- ❌ `def find(self, **filters)` — generic filter dictionaries; write specific methods
- ❌ Returning a tuple of dicts shaped for the API — that's the service's job
- ❌ Repositories calling other repositories — call services from services, repositories are leaf nodes

---

## 12. Service Layer

### 12.1 Responsibilities

A service:

- Orchestrates one **use case** (place order, register product, request OTP)
- Calls one or more repositories, validates, applies business rules
- Calls integrations (SMS, payment, storage) via their interfaces
- Raises domain errors (typed, in `app/core/errors.py`)
- Never imports FastAPI, Pydantic schemas, or HTTP types

### 12.2 Service shape

```python
# app/domain/orders/services.py
from uuid import UUID
from app.core.errors import OutOfStockError, ValidationError
from app.domain.catalog.repositories import ProductRepository
from app.domain.inventory.repositories import (
    InventoryBatchRepository, BranchProductRepository, StockMovementRepository,
)
from app.domain.orders.repositories import OrderRepository, CartRepository
from app.domain.orders.models import Order, OrderItem, OrderStatus, ...


class PlaceOrderService:
    def __init__(
        self,
        carts: CartRepository,
        orders: OrderRepository,
        products: ProductRepository,
        branch_products: BranchProductRepository,
        batches: InventoryBatchRepository,
        movements: StockMovementRepository,
    ) -> None:
        self.carts = carts
        self.orders = orders
        self.products = products
        self.branch_products = branch_products
        self.batches = batches
        self.movements = movements

    async def execute(
        self,
        *,
        user_id: UUID,
        cart_id: UUID,
        branch_id: int,
        address_snapshot: dict,
        payment_method: str,
        delivery_method: str,
        notes: str | None,
    ) -> Order:
        cart = await self.carts.get_with_items(cart_id, user_id)
        if cart is None or not cart.items:
            raise ValidationError("cart_empty")

        order = Order(
            id=uuid7(),
            user_id=user_id,
            branch_id=branch_id,
            ...
        )
        await self.orders.add(order)

        for item in cart.items:
            available = await self.branch_products.available_quantity(branch_id, item.product_id)
            if available < item.quantity:
                raise OutOfStockError(product_id=item.product_id, requested=item.quantity, available=available)

            remaining = item.quantity
            batches = await self.batches.list_for_fefo_locked(branch_id, item.product_id)
            for batch in batches:
                if remaining <= 0:
                    break
                consumed = min(batch.quantity_remaining, remaining)
                batch.quantity_remaining -= consumed
                remaining -= consumed

                await self.movements.add_reserved(
                    batch=batch, order_id=order.id, quantity=consumed,
                )
                order.items.append(OrderItem(
                    order_id=order.id,
                    product_id=item.product_id,
                    inventory_batch_id=batch.id,
                    product_name_snapshot=item.product_name_snapshot,
                    product_sku_snapshot=item.product_sku_snapshot,
                    batch_number_snapshot=batch.batch_number,
                    expiry_date_snapshot=batch.expiry_date,
                    quantity=consumed,
                    unit_price=item.price_snapshot,
                    line_total=item.price_snapshot * consumed,
                ))

            if remaining > 0:
                # Should not happen — we checked. Defensive.
                raise OutOfStockError(...)

            await self.branch_products.increment_reserved(
                branch_id, item.product_id, item.quantity,
            )

        # Totals, status history, etc.
        order.subtotal = sum(i.line_total for i in order.items)
        order.total = order.subtotal + order.delivery_fee - order.discount_amount
        return order
```

### 12.3 Rules

- One service class per use case OR one per aggregate with several methods. Pick the unit that reads best.
- Constructors take collaborators as arguments. The DI graph is wired in `app/api/deps.py`.
- Services return ORM models or domain DTOs. Pydantic happens in the router.
- All DB writes in a single service method run in one transaction (the request's). If you need a savepoint, use `async with session.begin_nested()`.
- Errors are typed: `OutOfStockError`, `InvalidOTPError`, `RateLimitExceededError`. Don't raise generic `ValueError`.

---

## 13. API Layer (Routers & Dependencies)

### 13.1 Router pattern

```python
# app/api/v1/catalog.py
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from app.api.deps import get_catalog_service, LangDep
from app.core.pagination import Page
from app.domain.catalog.schemas import ProductRead, ProductDetail
from app.domain.catalog.services import CatalogService

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/categories/{slug}/products", response_model=Page[ProductRead])
async def list_category_products(
    slug: str,
    lang: LangDep,
    service: Annotated[CatalogService, Depends(get_catalog_service)],
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
) -> Page[ProductRead]:
    return await service.list_by_category_slug(
        slug=slug, lang=lang, page=page, page_size=page_size,
    )


@router.get("/products/{slug}", response_model=ProductDetail)
async def get_product(
    slug: str,
    lang: LangDep,
    service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> ProductDetail:
    return await service.get_detail_by_slug(slug=slug, lang=lang)
```

### 13.2 Dependencies

```python
# app/api/deps.py
from typing import Annotated
from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.i18n import resolve_language
from app.domain.catalog.repositories import ProductRepository
from app.domain.catalog.services import CatalogService

DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_lang(accept_language: Annotated[str | None, Header()] = None) -> str:
    return resolve_language(accept_language)


LangDep = Annotated[str, Depends(get_lang)]


def get_product_repository(session: DbSession) -> ProductRepository:
    return ProductRepository(session)


def get_catalog_service(
    products: Annotated[ProductRepository, Depends(get_product_repository)],
) -> CatalogService:
    return CatalogService(products)
```

> **Wiring rule:** factories live in `app/api/deps.py`. Domain code never imports `Depends`.

### 13.3 Top-level router composition

```python
# app/api/v1/router.py
from fastapi import APIRouter
from app.api.v1 import auth, account, catalog, search, cart, checkout, orders, content

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(account.router)
router.include_router(catalog.router)
router.include_router(search.router)
router.include_router(cart.router)
router.include_router(checkout.router)
router.include_router(orders.router)
router.include_router(content.router)


# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from app.api.v1.router import router as v1_router
from app.api.admin_v1.router import router as admin_v1_router
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestIdMiddleware, AccessLogMiddleware
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.redis import close_redis, init_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    await init_redis(settings)
    yield
    await close_redis()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Pharmacy API",
        version="1.0.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.include_router(v1_router)
    app.include_router(admin_v1_router)
    register_exception_handlers(app)
    return app


app = create_app()
```

### 13.4 Router rules

- Routers depend on services, never on repositories or models directly.
- Routers do not catch domain exceptions — the exception handlers in `app/api/errors.py` translate them to HTTP responses.
- Every endpoint specifies `response_model` (for OpenAPI accuracy and FastAPI's response coercion).
- Path parameters are resolved by services where useful (e.g. by slug). Don't pass raw slugs around if you can pass the resolved entity.

---

## 14. Authentication & Authorization

### 14.1 Customer flow — SMS OTP + JWT

```python
# app/domain/identity/services.py — sketch
class OtpService:
    async def request_code(self, phone: str, ip: str) -> None:
        await self.rate_limiter.check_otp_request(phone, ip)
        code = generate_numeric_code(self.settings.otp_length)
        code_hash = hash_otp(code, self.settings.password_pepper.get_secret_value())
        await self.repo.create(
            phone=phone, code_hash=code_hash, ip=ip,
            ttl_seconds=self.settings.otp_ttl_seconds,
        )
        await self.queue.enqueue("send_sms", phone=phone,
                                 body=f"Your code: {code}", purpose="otp")

    async def verify_and_issue_tokens(self, phone: str, code: str) -> TokenPair:
        otp = await self.repo.get_active(phone)
        if otp is None:
            raise InvalidOTPError("not_found_or_expired")
        if otp.attempts >= otp.max_attempts:
            raise InvalidOTPError("too_many_attempts")
        if not verify_otp(code, otp.code_hash, self.settings.password_pepper.get_secret_value()):
            await self.repo.increment_attempts(otp.id)
            raise InvalidOTPError("wrong_code")
        await self.repo.consume(otp.id)

        user = await self.users.get_or_create_by_phone(phone)
        return self.tokens.issue_pair(subject=str(user.id), kind="customer")
```

### 14.2 Token issuance

```python
# app/core/security.py
from datetime import datetime, timedelta, timezone
from jose import jwt
from app.core.config import get_settings

class TokenIssuer:
    def __init__(self, settings):
        self.settings = settings

    def issue_pair(self, *, subject: str, kind: str) -> TokenPair:
        now = datetime.now(timezone.utc)
        access = jwt.encode(
            {
                "sub": subject, "kind": kind, "type": "access",
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=self.settings.jwt_access_ttl_minutes)).timestamp()),
                "jti": str(uuid7()),
            },
            self.settings.jwt_secret.get_secret_value(),
            algorithm=self.settings.jwt_algorithm,
        )
        refresh = ...  # similar, type=refresh, exp = days
        return TokenPair(access=access, refresh=refresh)
```

### 14.3 Current-user dependency

```python
# app/domain/identity/dependencies.py
from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from app.api.deps import DbSession, SettingsDep
from app.domain.identity.repositories import UserRepository

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: SettingsDep,
    session: DbSession,
):
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing_token")
    try:
        payload = jwt.decode(
            creds.credentials,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_token")
    if payload.get("type") != "access" or payload.get("kind") != "customer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong_token_type")
    user = await UserRepository(session).get_by_id(UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user_inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
```

### 14.4 Admin auth — server-side sessions

```python
# Browser login → POST /admin/auth/login
# Server: argon2 verify, optional TOTP, then:
#   1. Insert admin_sessions row (token = secrets.token_urlsafe(32), token_hash stored)
#   2. Set HttpOnly Secure SameSite=Lax cookie 'admin_session=<token>'
# Subsequent requests: middleware looks up by token_hash, attaches admin_user
```

### 14.5 RBAC dependency

```python
# app/domain/identity/dependencies.py (admin side)
def require_role(*allowed: AdminRole):
    async def _dep(admin: CurrentAdmin) -> AdminUser:
        if admin.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
        return admin
    return _dep


def require_branch_access(target_branch_id_param: str = "branch_id"):
    async def _dep(request: Request, admin: CurrentAdmin) -> AdminUser:
        if admin.role == AdminRole.SUPER_ADMIN:
            return admin
        target = int(request.path_params[target_branch_id_param])
        if admin.branch_id != target:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden_branch")
        return admin
    return _dep
```

Used in routes:

```python
@router.post("/products")
async def create_product(
    payload: ProductCreate,
    admin: Annotated[AdminUser, Depends(require_role(AdminRole.SUPER_ADMIN, AdminRole.CONTENT_EDITOR))],
    service: Annotated[CatalogAdminService, Depends(get_catalog_admin_service)],
):
    return await service.create(payload=payload, actor=admin)
```

### 14.6 Password & OTP hashing

```python
# app/core/security.py
from passlib.context import CryptContext

_pwd = CryptContext(schemes=["argon2"], argon2__type="ID",
                    argon2__memory_cost=65536, argon2__time_cost=3, argon2__parallelism=2)

def hash_password(plain: str, pepper: str) -> str:
    return _pwd.hash(plain + pepper)

def verify_password(plain: str, hashed: str, pepper: str) -> bool:
    return _pwd.verify(plain + pepper, hashed)


def hash_otp(code: str, pepper: str) -> str:
    # Short numeric OTPs benefit from pepper but argon2 is overkill;
    # HMAC-SHA256 is appropriate and constant-time.
    import hmac, hashlib
    return hmac.new(pepper.encode(), code.encode(), hashlib.sha256).hexdigest()

def verify_otp(code: str, hashed: str, pepper: str) -> bool:
    import hmac
    return hmac.compare_digest(hash_otp(code, pepper), hashed)
```


---

## 15. Validation, Errors & Exception Handling

### 15.1 Error hierarchy

```python
# app/core/errors.py
from typing import Any


class AppError(Exception):
    """Base for all application errors."""
    code: str = "internal_error"
    status_code: int = 500
    message: str = "Internal error"

    def __init__(self, message: str | None = None, **context: Any) -> None:
        super().__init__(message or self.message)
        self.context = context


class ValidationError(AppError):
    code = "validation_error"
    status_code = 400
    message = "Invalid input"


class AuthenticationError(AppError):
    code = "unauthorized"
    status_code = 401
    message = "Authentication required"


class PermissionDeniedError(AppError):
    code = "forbidden"
    status_code = 403
    message = "Permission denied"


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404
    message = "Resource not found"


class ConflictError(AppError):
    code = "conflict"
    status_code = 409
    message = "Conflict"


class RateLimitExceededError(AppError):
    code = "rate_limited"
    status_code = 429
    message = "Too many requests"


class OutOfStockError(ConflictError):
    code = "out_of_stock"


class InvalidOTPError(AuthenticationError):
    code = "invalid_otp"


class IdempotencyConflictError(ConflictError):
    code = "idempotency_conflict"
```

### 15.2 Centralised handlers

```python
# app/api/errors.py
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from sqlalchemy.exc import IntegrityError
from app.core.errors import AppError
from app.core.logging import get_logger

log = get_logger(__name__)


def _problem(status: int, code: str, title: str, detail: str | None = None, **extra) -> dict:
    return {
        "type": f"about:blank#{code}",
        "title": title,
        "status": status,
        "code": code,
        **({"detail": detail} if detail else {}),
        **extra,
    }


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return ORJSONResponse(
            status_code=exc.status_code,
            content=_problem(exc.status_code, exc.code, exc.message,
                             detail=str(exc), context=exc.context or None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return ORJSONResponse(
            status_code=422,
            content=_problem(422, "validation_error", "Invalid request",
                             errors=exc.errors()),
        )

    @app.exception_handler(IntegrityError)
    async def integrity_handler(request: Request, exc: IntegrityError):
        log.warning("integrity_error", error=str(exc.orig))
        return ORJSONResponse(
            status_code=409,
            content=_problem(409, "conflict", "Data conflict"),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.exception("unhandled_exception", path=str(request.url.path))
        return ORJSONResponse(
            status_code=500,
            content=_problem(500, "internal_error", "Internal error"),
        )
```

### 15.3 Rules

- **Routers don't try/except domain errors.** Let them propagate; handlers catch them.
- **One error type per business outcome.** `OutOfStockError` not "raise ValueError('out of stock')".
- **Never leak stack traces in responses.** Logs only.
- **Error responses follow RFC 7807** Problem Details (`type`, `title`, `status`, `detail`, `code`).

---

## 16. Middleware & Cross-cutting Concerns

### 16.1 Request ID

```python
# app/api/middleware.py
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.core.logging import bind_context, clear_context, get_logger

log = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        bind_context(request_id=rid, path=request.url.path, method=request.method)
        try:
            response = await call_next(request)
            response.headers["x-request-id"] = rid
            return response
        finally:
            clear_context()


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000
        log.info(
            "http_request",
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response
```

### 16.2 CORS

Configured in `main.py` from `settings.cors_origins`. Allowed methods restricted; credentials allowed only for admin SPA origin.

### 16.3 Trusted hosts

Use `TrustedHostMiddleware` in production with explicit hosts.

### 16.4 GZip

`GZipMiddleware(minimum_size=1000)` — small enough to skip tiny payloads, big enough to win on catalog responses.

### 16.5 Order of middleware

```python
app.add_middleware(RequestIdMiddleware)        # outermost — every log gets a request_id
app.add_middleware(AccessLogMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, ...)
app.add_middleware(TrustedHostMiddleware, ...) # innermost
```

---

## 17. Background Jobs (ARQ)

### 17.1 Why ARQ

- Async-native (matches our app)
- Redis-backed (we already run Redis)
- Supports cron-like schedules
- Lightweight ops vs Celery

If we outgrow it (multi-broker, heavy scheduling, monitoring needs), Celery is the migration target.

### 17.2 Worker settings

```python
# app/workers/settings.py
from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import get_settings
from app.workers import sms, images, imports, reports, scheduled

settings = get_settings()


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(str(settings.redis_dsn))
    functions = [
        sms.send_sms,
        images.process_image_upload,
        imports.process_product_import,
        reports.generate_admin_report,
    ]
    cron_jobs = [
        cron(scheduled.near_expiry_report, hour=6, minute=0),
        cron(scheduled.low_stock_report,    hour=6, minute=10),
        cron(scheduled.expire_batches,      hour=2, minute=0),
        cron(scheduled.reconcile_stock_cache, hour=3, minute=0),
        cron(scheduled.cleanup_otps,         hour=4, minute=0),
        cron(scheduled.cleanup_carts,        hour=4, minute=10),
        cron(scheduled.release_pending_orders, minute=0),     # hourly
        cron(scheduled.payment_reconcile,    minute=15),      # hourly
    ]
    max_jobs = 10
    job_timeout = 300                  # 5 minutes default
    keep_result = 3600
    max_tries = 5

    async def on_startup(ctx):
        from app.core.logging import configure_logging
        configure_logging(settings)

    async def on_shutdown(ctx):
        pass
```

### 17.3 Job pattern

Jobs are thin wrappers that open a session and call domain services.

```python
# app/workers/sms.py
from app.core.db import session_scope
from app.core.logging import get_logger
from app.integrations.sms.base import get_sms_client
from app.domain.ops.repositories import SmsLogRepository

log = get_logger(__name__)


async def send_sms(ctx, *, phone: str, body: str, purpose: str) -> None:
    client = get_sms_client()
    async with session_scope() as session:
        repo = SmsLogRepository(session)
        row = await repo.create_queued(phone=phone, body=body, purpose=purpose)
        try:
            result = await client.send(phone=phone, body=body)
            await repo.mark_sent(row.id, provider_message_id=result.message_id, cost=result.cost)
        except Exception as e:
            await repo.mark_failed(row.id, error=str(e))
            raise            # ARQ will retry per max_tries
```

### 17.4 Enqueueing from the API

```python
# app/api/deps.py
from arq import create_pool
from arq.connections import RedisSettings

_pool = None

async def get_arq_pool():
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(str(get_settings().redis_dsn)))
    return _pool

# Usage in a service
await pool.enqueue_job("send_sms", phone=phone, body=body, purpose="otp")
```

### 17.5 Job rules

- **Idempotent.** Re-running a job must produce the same end state. Use natural keys, `INSERT IGNORE`, status checks.
- **Job arguments are JSON-serialisable.** No ORM models, no `datetime` without ISO-format.
- **Don't pass session through `ctx`.** Open one per job in `session_scope()`.
- **Fail loudly.** Raise on error; ARQ retries with exponential backoff. Don't swallow exceptions.
- **Long jobs (>5 min)** stream progress via Redis hash and split into chunks.

---

## 18. Caching (Redis)

### 18.1 Client

```python
# app/core/redis.py
from redis.asyncio import Redis, from_url
from app.core.config import Settings

_redis: Redis | None = None


async def init_redis(settings: Settings) -> None:
    global _redis
    _redis = from_url(str(settings.redis_dsn), decode_responses=True,
                      health_check_interval=30)


async def close_redis() -> None:
    if _redis is not None:
        await _redis.close()


def get_redis() -> Redis:
    assert _redis is not None, "Redis not initialised"
    return _redis
```

### 18.2 Key conventions

```
v1:cat:tree:<lang>
v1:product:read:<uuid>:<lang>
v1:product:price:<branch_id>:<uuid>
v1:search:suggest:<lang>:<query>
v1:rl:otp:phone:<e164>
v1:rl:otp:ip:<ip>
v1:session:refresh:<jti>
v1:idem:<key>:<user_id>
```

The `v1:` prefix lets us purge the whole cache namespace on a serialisation change.

### 18.3 Cache helpers

```python
# app/core/cache.py
import orjson
from typing import Awaitable, Callable, TypeVar
from app.core.redis import get_redis

T = TypeVar("T")


async def cache_get_or_set(
    key: str,
    ttl: int,
    loader: Callable[[], Awaitable[T]],
    serializer=orjson.dumps,
    deserializer=orjson.loads,
) -> T:
    r = get_redis()
    raw = await r.get(key)
    if raw is not None:
        return deserializer(raw)
    value = await loader()
    await r.set(key, serializer(value), ex=ttl)
    return value


async def invalidate(prefix: str) -> None:
    r = get_redis()
    async for k in r.scan_iter(match=f"{prefix}*", count=500):
        await r.delete(k)
```

### 18.4 What is cached and what is not

| Cached | TTL | Invalidated on |
|---|---|---|
| Categories tree per language | 1h | Category mutation → `invalidate("v1:cat:tree:")` |
| Product detail (read model) | 5 min | Product/translation/image update for that ID |
| Featured products (homepage) | 10 min | Time-based + on `is_featured` toggle |
| Search suggestions | 60s | Time-based |
| Rate-limit counters | sliding | Native expiry |

| Never cached |
|---|
| Real-time inventory (cart, checkout reads it fresh) |
| Order status |
| Anything in admin endpoints |
| Anything tied to an authenticated user's identity |

### 18.5 Rate limiting helper

```python
# app/core/ratelimit.py
import time
from app.core.errors import RateLimitExceededError
from app.core.redis import get_redis


async def hit(*, key: str, limit: int, window_seconds: int) -> None:
    r = get_redis()
    now = int(time.time())
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds)
    count, _ = await pipe.execute()
    if int(count) > limit:
        raise RateLimitExceededError(key=key, limit=limit, window=window_seconds)
```

---

## 19. Logging

### 19.1 Configuration

```python
# app/core/logging.py
import logging
import sys
import structlog
from contextvars import ContextVar
from app.core.config import Settings

_ctx: ContextVar[dict] = ContextVar("log_ctx", default={})


def bind_context(**kwargs) -> None:
    _ctx.set({**_ctx.get(), **kwargs})


def clear_context() -> None:
    _ctx.set({})


def _ctx_processor(_, __, event_dict):
    event_dict.update(_ctx.get())
    return event_dict


def configure_logging(settings: Settings) -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    pre_chain = [
        structlog.contextvars.merge_contextvars,
        _ctx_processor,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
    ]

    structlog.configure(
        processors=[
            *pre_chain,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.debug else logging.INFO
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)


def get_logger(name: str):
    return structlog.get_logger(name)
```

### 19.2 Rules

- **Always use `get_logger(__name__)`.** Never `print()`.
- **Structured fields, not f-strings.** `log.info("order_placed", order_id=..., total=...)`, not `log.info(f"placed {x}")`.
- **PII redaction.** Phone numbers logged as last 4 only. OTP codes never logged. Passwords never logged.
- **Levels:**
  - `DEBUG`: developer-only details
  - `INFO`: ordinary lifecycle events (`order_placed`, `payment_succeeded`)
  - `WARNING`: recoverable anomaly (`integrity_error`, `payment_retry`)
  - `ERROR`: failed operation (`sms_send_failed`)
  - `CRITICAL`: data-loss territory; pager-worthy
- **Every request log line carries `request_id`** via `RequestIdMiddleware`.

---

## 20. Pagination, Filtering, Sorting

### 20.1 Offset (catalog)

```python
# Query param contract
?page=1&page_size=24&sort=name|-created_at,price
```

```python
# app/core/pagination.py — additions
from typing import Annotated
from fastapi import Query
from pydantic import BaseModel

class PageParams(BaseModel):
    page: int = 1
    page_size: int = 24

def page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


def offset_limit(p: PageParams) -> tuple[int, int]:
    return (p.page - 1) * p.page_size, p.page_size
```

### 20.2 Cursor (orders, audit log, anything append-mostly)

```
?cursor=eyJpZCI6IjAxOTM..."&limit=20
```

The cursor is base64-encoded JSON of the last seen `(created_at, id)` tuple. Queries use the keyset:

```python
where_clause = or_(
    Order.created_at < cursor.created_at,
    and_(Order.created_at == cursor.created_at, Order.id < cursor.id),
)
```

### 20.3 Sorting

Allow-list sortable fields per endpoint:

```python
ALLOWED_PRODUCT_SORTS = {"name", "price", "created_at"}

def parse_sort(value: str | None, allowed: set[str]) -> list[tuple[str, bool]]:
    if not value:
        return []
    out = []
    for raw in value.split(","):
        raw = raw.strip()
        desc = raw.startswith("-")
        field = raw.lstrip("-+")
        if field not in allowed:
            raise ValidationError(f"sort_not_allowed:{field}")
        out.append((field, desc))
    return out
```

### 20.4 Filtering

Each endpoint declares filters explicitly via Pydantic. **No "generic filter expression" parsers.** Whitelist beats flexibility.

---

## 21. Idempotency

POSTs that create money-relevant resources (orders, payments) accept an `Idempotency-Key` header.

### 21.1 Mechanism

1. Client sends header `Idempotency-Key: <uuid>` and a body.
2. Service computes `digest = sha256(method + path + body)`.
3. Looks up `v1:idem:<key>:<user_id>` in Redis.
   - **Hit, same digest** → return the stored response (200/201 with original payload).
   - **Hit, different digest** → return `409 idempotency_conflict`.
   - **Miss** → set a stub with TTL, execute the request, then write the final response under the key with TTL = 24h.
4. The stored response includes status, headers (selected), and body.

### 21.2 Where it's enforced

- Required: `POST /checkout/place`, `POST /admin/orders/:id/refund`, `POST /admin/products/import`
- Recommended: any other money-side mutation

### 21.3 Implementation note

Idempotency-Key state is stored in Redis with the response payload — **not in MySQL** — to keep the OLTP DB lean.

---

## 22. Internationalization

### 22.1 Language resolution

```python
# app/core/i18n.py
from app.core.config import get_settings


def resolve_language(accept_language: str | None) -> str:
    settings = get_settings()
    if not accept_language:
        return settings.default_language
    # Parse "ru-RU,ru;q=0.9,en;q=0.8" and pick first supported
    for token in accept_language.split(","):
        code = token.split(";")[0].strip().lower().split("-")[0]
        if code in settings.supported_languages:
            return code
    return settings.default_language
```

User profile language overrides the header for authenticated users.

### 22.2 Loading translations from DB

The catalog returns text in the resolved language. Service-layer pattern:

```python
def pick_translation(rows: list[ProductTranslation], lang: str, fallback: str) -> ProductTranslation:
    by_lang = {r.language_code: r for r in rows}
    return by_lang.get(lang) or by_lang.get(fallback) or rows[0]
```

### 22.3 Outbound copy (SMS, emails)

Per-language templates in code (not DB) for MVP. Template selection by user's `preferred_language` or order recipient's language hint.

---

## 23. Testing

### 23.1 Layout

```
tests/
├── conftest.py               # fixtures: app, db, redis, factories
├── factories/                # factory_boy factories
│   ├── __init__.py
│   ├── identity.py
│   ├── catalog.py
│   └── orders.py
├── unit/                     # service & repository tests, no HTTP
│   └── ...
├── integration/              # repository against real MySQL, services with real DB
│   └── ...
└── e2e/                      # full HTTP via httpx.AsyncClient against the app
    └── ...
```

### 23.2 Core fixtures

```python
# tests/conftest.py
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db_base import Base
from app.main import create_app


TEST_DSN = "mysql+asyncmy://test:test@localhost:3306/pharmacy_test"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    engine = create_async_engine(TEST_DSN, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncSession:
    """One session per test, rolled back at the end."""
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        try:
            yield s
        finally:
            await s.rollback()


@pytest_asyncio.fixture
async def client(session):
    app = create_app()
    # override get_db so the test session is used
    from app.core.db import get_db
    app.dependency_overrides[get_db] = lambda: session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
```

### 23.3 Test categories

| Layer | Tool | What is mocked |
|---|---|---|
| Repository | real MySQL | nothing |
| Service | real MySQL via repos | external integrations (SMS, payment, storage) — use `fake.py` |
| Router | full app via httpx | external integrations |
| Worker | real MySQL via session_scope | external integrations |

### 23.4 Test conventions

- Test names describe the behaviour: `test_place_order_succeeds_when_stock_sufficient`, `test_place_order_raises_out_of_stock_when_insufficient`.
- One assertion focus per test.
- Use factories for setup. Don't manually build aggregates row-by-row.
- Use `freezegun` for time-sensitive logic (OTP expiry, near-expiry reports).
- E2E tests exercise the full HTTP flow including auth.

### 23.5 Coverage

- Target ≥ 85% line coverage on `app/domain/` and `app/api/`
- Coverage is informational, not gating — meaningful tests beat coverage padding

---

## 24. Code Quality (lint, type-check, format)

### 24.1 Tooling

| Tool | Purpose | Config |
|---|---|---|
| **ruff** | linter + formatter | `pyproject.toml` |
| **mypy** | type-check (strict) | `pyproject.toml` |
| **pre-commit** | run all of the above on commit | `.pre-commit-config.yaml` |

### 24.2 ruff config

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = [
    "E", "F", "W",      # pycodestyle, pyflakes
    "I",                # isort
    "B",                # flake8-bugbear
    "UP",               # pyupgrade
    "N",                # pep8-naming
    "S",                # bandit (security)
    "ASYNC",            # async correctness
    "C4",               # comprehensions
    "RET",              # returns
    "SIM",              # simplifications
    "TID",              # tidy imports
    "PL",               # pylint subset
    "RUF",              # ruff-specific
]
ignore = ["S101", "PLR0913"]   # allow assert in tests; allow many args (DI)

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S", "PLR2004"]
"migrations/**" = ["E501", "I"]
```

### 24.3 mypy config

```toml
[tool.mypy]
python_version = "3.12"
strict = true
warn_unreachable = true
warn_unused_ignores = true
no_implicit_reexport = true
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = ["asyncmy.*", "arq.*"]
ignore_missing_imports = true
```

### 24.4 Pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.13.0
    hooks:
      - id: mypy
        additional_dependencies:
          - pydantic>=2.9
          - sqlalchemy>=2.0
        args: [--strict]
        files: ^app/
```

### 24.5 Type-hint rules

- Every public function has a return type.
- `None` returns are explicit (`-> None`).
- Use `from __future__ import annotations` at the top of every module.
- Prefer `list[X]` over `List[X]`, `X | None` over `Optional[X]`.
- For generics, `Annotated[X, ...]` is preferred over default-value `Field(...)` shapes.
- ORM relationships use `Mapped[list["Other"]]` with string forward refs.

---

## 25. Local Development (docker-compose)

```yaml
# docker-compose.yml
services:
  mysql:
    image: mysql:8.4
    command: >
      --character-set-server=utf8mb4
      --collation-server=utf8mb4_0900_ai_ci
      --default-authentication-plugin=caching_sha2_password
      --sql-mode=STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO
      --innodb-default-row-format=DYNAMIC
      --ngram-token-size=2
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: pharmacy
      MYSQL_USER: pharmacy
      MYSQL_PASSWORD: pharmacy
    ports: ["3306:3306"]
    volumes: ["mysql_data:/var/lib/mysql"]
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-uroot", "-proot"]
      interval: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s

  api:
    build: .
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    env_file: .env
    depends_on:
      mysql: { condition: service_healthy }
      redis: { condition: service_healthy }
    ports: ["8000:8000"]
    volumes: ["./:/app"]

  worker:
    build: .
    command: arq app.workers.settings.WorkerSettings
    env_file: .env
    depends_on:
      mysql: { condition: service_healthy }
      redis: { condition: service_healthy }
    volumes: ["./:/app"]

volumes:
  mysql_data:
```

```dockerfile
# Dockerfile (production)
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libssl-dev curl \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

COPY . .

EXPOSE 8000
CMD ["gunicorn", "app.main:app",
     "-k", "uvicorn.workers.UvicornWorker",
     "-w", "4", "-b", "0.0.0.0:8000",
     "--access-logfile", "-", "--error-logfile", "-"]
```

### 25.1 Make targets

```makefile
# Makefile
.PHONY: install dev test lint type fmt migrate revision worker

install:
	uv sync

dev:
	docker compose up -d mysql redis
	uvicorn app.main:app --reload

test:
	pytest -q

lint:
	ruff check app tests
	ruff format --check app tests

type:
	mypy app

fmt:
	ruff check --fix app tests
	ruff format app tests

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

worker:
	arq app.workers.settings.WorkerSettings
```

---

## 26. Vertical Slice — End-to-End Example

The full path of `POST /api/v1/auth/otp/request` to demonstrate every layer.

### 26.1 Schema

```python
# app/domain/identity/schemas.py
from pydantic import BaseModel, ConfigDict, field_validator
from app.core.security import normalise_phone

class OtpRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalise_phone(v)


class OtpRequestOut(BaseModel):
    sent: bool
    expires_in_seconds: int
```

### 26.2 Repository

```python
# app/domain/identity/repositories.py (extract)
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.domain.identity.models import OtpCode

class OtpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, phone: str, code_hash: str, ttl_seconds: int, ip: str | None) -> OtpCode:
        otp = OtpCode(
            phone=phone, code_hash=code_hash,
            purpose="login",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
            ip_address=ip,
        )
        self.session.add(otp)
        await self.session.flush()
        return otp

    async def get_active(self, phone: str) -> OtpCode | None:
        stmt = (
            select(OtpCode)
            .where(
                OtpCode.phone == phone,
                OtpCode.consumed_at.is_(None),
                OtpCode.expires_at > datetime.now(timezone.utc),
            )
            .order_by(OtpCode.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
```

### 26.3 Service

```python
# app/domain/identity/services.py (extract)
import secrets
from arq.connections import ArqRedis
from app.core.config import Settings
from app.core.errors import RateLimitExceededError
from app.core.ratelimit import hit
from app.core.security import hash_otp
from app.domain.identity.repositories import OtpRepository


class OtpService:
    def __init__(self, settings: Settings, repo: OtpRepository, queue: ArqRedis) -> None:
        self.settings = settings
        self.repo = repo
        self.queue = queue

    async def request_code(self, *, phone: str, ip: str | None) -> int:
        await hit(
            key=f"v1:rl:otp:phone:{phone}",
            limit=self.settings.rl_otp_request_per_phone_max,
            window_seconds=self.settings.rl_otp_request_per_phone_window_seconds,
        )
        code = "".join(secrets.choice("0123456789") for _ in range(self.settings.otp_length))
        code_hash = hash_otp(code, self.settings.password_pepper.get_secret_value())
        await self.repo.create(
            phone=phone, code_hash=code_hash,
            ttl_seconds=self.settings.otp_ttl_seconds, ip=ip,
        )
        await self.queue.enqueue_job(
            "send_sms", phone=phone, body=f"Pharmacy code: {code}", purpose="otp",
        )
        return self.settings.otp_ttl_seconds
```

### 26.4 Dependency wiring

```python
# app/api/deps.py (extract)
def get_otp_repository(session: DbSession) -> OtpRepository:
    return OtpRepository(session)


async def get_otp_service(
    settings: SettingsDep,
    repo: Annotated[OtpRepository, Depends(get_otp_repository)],
    pool: Annotated[ArqRedis, Depends(get_arq_pool)],
) -> OtpService:
    return OtpService(settings=settings, repo=repo, queue=pool)
```

### 26.5 Router

```python
# app/api/v1/auth.py
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from app.api.deps import get_otp_service
from app.domain.identity.schemas import OtpRequestIn, OtpRequestOut
from app.domain.identity.services import OtpService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/otp/request", response_model=OtpRequestOut, status_code=202)
async def request_otp(
    payload: OtpRequestIn,
    request: Request,
    service: Annotated[OtpService, Depends(get_otp_service)],
) -> OtpRequestOut:
    ttl = await service.request_code(phone=payload.phone, ip=request.client.host if request.client else None)
    return OtpRequestOut(sent=True, expires_in_seconds=ttl)
```

### 26.6 Test

```python
# tests/e2e/test_auth_otp.py
import pytest

@pytest.mark.asyncio
async def test_request_otp_creates_row_and_enqueues_job(client, session, mock_arq_pool, mock_sms_client):
    resp = await client.post("/api/v1/auth/otp/request", json={"phone": "+996700123456"})
    assert resp.status_code == 202
    assert resp.json() == {"sent": True, "expires_in_seconds": 300}
    # Repository view
    from sqlalchemy import select
    from app.domain.identity.models import OtpCode
    rows = (await session.execute(select(OtpCode))).scalars().all()
    assert len(rows) == 1
    assert rows[0].phone == "+996700123456"
    # Job enqueued
    mock_arq_pool.enqueue_job.assert_called_once()


@pytest.mark.asyncio
async def test_request_otp_rate_limits_after_three_requests(client, freezer):
    payload = {"phone": "+996700111222"}
    for _ in range(3):
        ok = await client.post("/api/v1/auth/otp/request", json=payload)
        assert ok.status_code == 202
    rate_limited = await client.post("/api/v1/auth/otp/request", json=payload)
    assert rate_limited.status_code == 429
    body = rate_limited.json()
    assert body["code"] == "rate_limited"
```

---

## 27. Conventions Checklist for Claude Code

Before declaring a task complete, every change must satisfy:

### 27.1 Structure
- [ ] New code lives in the correct layer (`api/`, `domain/<context>/`, `core/`, `workers/`, `integrations/`)
- [ ] Imports respect direction: `api → domain → core`. Domain never imports `api`. Core never imports anything.
- [ ] One bounded context per `domain/` folder; no cross-context model imports without going through a service

### 27.2 Models & DB
- [ ] New table includes `created_at`, `updated_at` via `TimestampMixin`
- [ ] Soft-deletable entity uses `SoftDeleteMixin`
- [ ] FKs declared with `ondelete=` and a named constraint
- [ ] All indexes named `idx_/uq_/chk_/fk_` per §4
- [ ] Money columns are `Numeric(12, 2)`
- [ ] Datetimes are `DateTime(6)` and stored UTC
- [ ] Enums use Python `StrEnum` mapped to `String(32)` + `CHECK`
- [ ] `__table_args__` includes `mysql_engine`, `mysql_charset`, `mysql_collate`
- [ ] Relationships use `lazy="raise"` unless there's a documented reason otherwise
- [ ] Alembic migration generated, reviewed, and applies cleanly up and down

### 27.3 Schemas (Pydantic)
- [ ] Separate `Create` / `Update` / `Read` schemas
- [ ] `model_config = ConfigDict(extra="forbid")` on all input schemas
- [ ] `model_config = ConfigDict(from_attributes=True)` on all `Read` schemas
- [ ] No ORM models leak into responses

### 27.4 Layers
- [ ] Routers don't contain business logic
- [ ] Services don't import FastAPI
- [ ] Repositories don't commit, don't open sessions, don't return Pydantic
- [ ] No raw SQL outside repositories
- [ ] Cross-aggregate work goes through services, not repository-to-repository

### 27.5 Async correctness
- [ ] Every IO function is `async def`
- [ ] No sync DB calls in async handlers
- [ ] No blocking calls (`time.sleep`, `requests`) — use `asyncio.sleep` and `httpx`

### 27.6 Errors
- [ ] Domain errors are typed (`OutOfStockError`, etc.), not `ValueError`
- [ ] Routers do not catch domain errors
- [ ] Error responses follow the Problem Details shape

### 27.7 Auth & security
- [ ] Endpoints state their auth requirement (`Depends(get_current_user)` or `require_role(...)`)
- [ ] Admin actions write `admin_audit_log` entries
- [ ] Sensitive headers/fields scrubbed from logs
- [ ] No secrets in code or commit messages

### 27.8 Tests
- [ ] At least one test per new endpoint, covering happy path
- [ ] At least one test per service for domain rules (e.g., out-of-stock)
- [ ] External integrations are faked (`integrations/.../fake.py`), not patched ad-hoc
- [ ] Tests do not depend on test order

### 27.9 Quality
- [ ] `ruff check` clean
- [ ] `ruff format --check` clean
- [ ] `mypy --strict app` clean
- [ ] No new `# type: ignore` without an inline justification

### 27.10 Performance
- [ ] No N+1: relationships are explicitly loaded with `selectinload`/`joinedload`
- [ ] List endpoints have a covering index (verified with `EXPLAIN`)
- [ ] Hot paths (catalog list, search) cache where indicated in §18

### 27.11 Background jobs
- [ ] New job is registered in `WorkerSettings.functions`
- [ ] Job arguments are JSON-serialisable
- [ ] Job is idempotent
- [ ] Scheduled jobs are added to `cron_jobs` with explicit times

### 27.12 i18n
- [ ] User-facing text resolves through translations / templates
- [ ] No hardcoded RU/KY/EN strings in routers or services

### 27.13 Documentation
- [ ] OpenAPI tags and `summary` / `description` set on each endpoint
- [ ] Non-obvious decisions have a comment referencing this doc's section

---

*Document version 1.0 — Pharmacy Platform backend blueprint, FastAPI + SQLAlchemy + MySQL.*

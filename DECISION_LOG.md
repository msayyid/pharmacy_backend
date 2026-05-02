# Decision Log

> Non-obvious choices and their rationale. Future-you reading this should
> understand why something was done a particular way without re-deriving
> it. **Append-only; never edit past entries.**

## Format

Each entry:

```
### YYYY-MM-DD — Short title
**Phase:** N
**Context:** What was the situation?
**Decision:** What was chosen?
**Alternatives considered:** What else was on the table?
**Rationale:** Why this one?
**Trade-offs:** What did we lose by choosing this?
**Reversibility:** Easy / hard / one-way
**References:** Spec section(s) or PR
```

---

### 2026-05-02 — uv as the package manager
**Phase:** 1
**Context:** `BACKEND §2` lists deps in PEP 621 + 735 format (uv-native); `BACKEND §25` Makefile uses `uv sync` and Dockerfile uses `uv`. Phase 0 plan flagged it for confirmation.
**Decision:** uv with `pyproject.toml` + committed `uv.lock`. Local install via `make install` → `uv sync`.
**Alternatives considered:** poetry, pip-tools.
**Rationale:** Every spec touch-point assumes uv; switching would require rewriting the Makefile and Dockerfile. uv is significantly faster and has good Docker layer caching.
**Trade-offs:** Newer than poetry; team must learn `uv sync` / `uv run` semantics.
**Reversibility:** Easy — both formats produce a lockfile and respect `pyproject.toml`.
**References:** BACKEND §2, §25; BUILD_PLAN.md §1.

---

### 2026-05-02 — Single multistage Dockerfile (builder → runtime)
**Phase:** 1
**Context:** Phase 1 prompt asked whether to use one multistage Dockerfile or separate dev/prod ones.
**Decision:** Single multistage Dockerfile. `builder` stage installs deps via uv; `runtime` stage ships only `.venv` + `app/` under a non-root user with healthcheck. Local dev overrides `command:` in compose to use `uvicorn --reload`.
**Alternatives considered:** Separate `Dockerfile.dev` + `Dockerfile.prod`.
**Rationale:** Single source of truth for system deps and Python pin. Compose can override CMD; one image to maintain.
**Trade-offs:** Image build for dev pulls all production system libs (small cost).
**Reversibility:** Easy.
**References:** BACKEND §25; BUILD_PLAN.md §1.

---

### 2026-05-02 — FastAPI ``lifespan`` async context manager (not deprecated startup events)
**Phase:** 1
**Context:** FastAPI deprecated `@app.on_event("startup"/"shutdown")` in favour of an async context manager.
**Decision:** Use `@asynccontextmanager async def lifespan(app)`.
**Alternatives considered:** Legacy startup events.
**Rationale:** Modern FastAPI idiom; matches BACKEND §13.3.
**Trade-offs:** None.
**Reversibility:** Easy.
**References:** BACKEND §13.3.

---

### 2026-05-02 — Sentry SDK no-op when DSN absent
**Phase:** 1
**Context:** Phase 1 spec required "Sentry SDK initialised but not capturing (DSN optional)".
**Decision:** Always call `sentry_sdk.init(dsn=None or settings.sentry_dsn.get_secret_value(), ...)`. Per Sentry SDK contract, `dsn=None` makes the SDK a no-op (no network calls, no captures). `send_default_pii=False`.
**Alternatives considered:** Skip `init` entirely when DSN absent and gate on env var.
**Rationale:** Init unconditionally so production envs that add the DSN later don't need code changes; the SDK's own no-op contract handles the "off" state.
**Trade-offs:** Negligible memory for the inactive SDK.
**Reversibility:** Easy.
**References:** BACKEND §19.2.

---

### 2026-05-02 — PII redaction by structured-field name (not by value pattern)
**Phase:** 1
**Context:** CLAUDE.md sacred invariant: "PII never logs in plaintext." Implementation choice: redact by field NAME (deterministic) vs by VALUE PATTERN (regex-based, fragile).
**Decision:** structlog processor `redact_pii` runs in the chain. Full-redact (`<redacted>`) for `password`, `password_hash`, `code`, `otp`, `otp_code`, `token`, `access_token`, `refresh_token`, `jwt`, `secret`, `api_key`, `authorization`, `cookie`, `set-cookie`. Phone-mask (`+996****NNNN`) for `phone`, `recipient_phone`, `courier_phone`, `contact_phone`. Match is case-insensitive on field names.
**Alternatives considered:** Redact by value pattern (regex for E.164, hex tokens) — rejected as fragile and slow. Redact via Sentry `before_send` only — rejected because it doesn't cover stdlib log lines.
**Rationale:** Field-name redaction is deterministic and unit-testable. Pairs with the discipline of structured logging — emit fields, never embed PII in `event` strings.
**Trade-offs:** Code discipline required: never log `f"phone {phone}"`. Caught by review and the redaction unit tests.
**Reversibility:** Easy — extend `_FULL_REDACT_FIELDS` / `_PHONE_FIELDS` set.
**References:** BACKEND §19.2; PHARMACY §20.4; CLAUDE.md "Sacred invariants" §5.

---

### 2026-05-02 — Middleware: RequestIdMiddleware added LAST so it is OUTERMOST
**Phase:** 1
**Context:** `BACKEND §16.5` lists middleware top-to-bottom as outermost-to-innermost (RequestId outermost). But Starlette's `add_middleware` *prepends* to the user middleware list — so the LAST `add_middleware` call ends up OUTERMOST.
**Decision:** Call `add_middleware` in reverse-of-spec-listing order (CORS → GZip → AccessLog → RequestId). RequestId is the LAST `add_middleware`, becoming the outermost. Verified empirically: a `GET /health` produces a single `http_request` log line that includes the bound `request_id` field.
**Alternatives considered:** Match the spec listing order verbatim. This would have put RequestId innermost, breaking the spec's stated INTENT.
**Rationale:** Follow the spec's intent (RequestId outermost), not the spec's example call ordering which is opposite to Starlette semantics.
**Trade-offs:** One small documented deviation from the spec example. `app/main.py` has an explicit comment block explaining the ordering.
**Reversibility:** Trivial flip.
**References:** BACKEND §16.5; Starlette source (`Starlette.add_middleware` uses `insert(0, ...)`).

---

### 2026-05-02 — Drop deprecated ``--default-authentication-plugin`` flag for MySQL 8.4
**Phase:** 1
**Context:** `BACKEND §25` docker-compose passed `--default-authentication-plugin=caching_sha2_password` to mysqld. MySQL 8.4 removed this variable (caching_sha2_password is the default; the variable is no longer accepted). On first boot the container exited with `unknown variable` and an unusable data directory.
**Decision:** Remove the flag from both `mysql` and `mysql-test` services in `docker-compose.yml`.
**Alternatives considered:** Pin to `mysql:8.0` — rejected; spec explicitly calls for `mysql:8.4`.
**Rationale:** caching_sha2_password is the default in 8.4; the flag is a no-op deprecation that aborts startup.
**Trade-offs:** None.
**Reversibility:** Easy if reverting to 8.0.
**References:** BACKEND §25; MySQL 8.4 release notes.

---

### 2026-05-02 — ``sql_mode`` aligned to CLAUDE.md (stricter than BACKEND §25)
**Phase:** 1
**Context:** `BACKEND §25` set `sql_mode=STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO`. `CLAUDE.md` "Tech stack reality checks" specified `STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ONLY_FULL_GROUP_BY,ERROR_FOR_DIVISION_BY_ZERO`. The two specs disagreed.
**Decision:** Adopt CLAUDE.md's set. `STRICT_TRANS_TABLES` is the more typical baseline for InnoDB; `ONLY_FULL_GROUP_BY` surfaces non-standard GROUP BY usage at query-write time.
**Alternatives considered:** BACKEND §25 set; superset.
**Rationale:** CLAUDE.md is the project-rulebook meta-document and is stricter. Stricter SQL mode catches more bugs early.
**Trade-offs:** Some queries that would work under STRICT_ALL_TABLES + missing ONLY_FULL_GROUP_BY may fail. We accept the upfront pain.
**Reversibility:** Easy — flag flip in `docker-compose.yml` + CI.
**References:** CLAUDE.md "Tech stack reality checks > Database is MySQL 8"; BACKEND §25.

---

### 2026-05-02 — Use MySQL dialect's ``DATETIME(fsp=6)`` for fractional seconds
**Phase:** 1
**Context:** `BACKEND §6.6` example used `DateTime(6)` — but SQLAlchemy core's `DateTime` takes `timezone: bool` as the first positional argument, not fsp. Microsecond precision requires the MySQL dialect's `DATETIME` type. mypy strict caught this.
**Decision:** `app/core/db_base.py` imports `from sqlalchemy.dialects.mysql import DATETIME` and uses `DATETIME(fsp=6)` for `created_at`, `updated_at`, `deleted_at` mixin columns.
**Alternatives considered:** `DateTime(timezone=False)` — rejected, defaults to second precision on MySQL. `Numeric` for unix-timestamp microseconds — overkill.
**Rationale:** Microsecond precision is required for time-ordered UUID7 + paired `stock_movements` ordering; the MySQL dialect type is the right tool.
**Trade-offs:** Module slightly less portable to other DBs — acceptable since we're MySQL-only.
**Reversibility:** Easy if migrating to Postgres (use `TIMESTAMP(6)` or `TIMESTAMPTZ`).
**References:** BACKEND §6.6; SQLAlchemy core `DateTime` vs `mysql.DATETIME`.

---

### 2026-05-02 — Test MySQL on port 3307 (tmpfs); dev MySQL on 3306 (volume)
**Phase:** 1
**Context:** Tests should not contend with dev DB and should tear down fast.
**Decision:** `mysql-test` service in docker-compose is profile-gated (`--profile test`), uses `tmpfs` for `/var/lib/mysql`, exposes 3307 on the host. `.env.test` references `mysql+asyncmy://test:test@localhost:3307/pharmacy_test`. Dev MySQL stays on 3306 with persistent volume `mysql_data`.
**Alternatives considered:** Single MySQL with multiple databases. Schema-per-test isolation.
**Rationale:** Hard isolation; tmpfs makes test-DB resets near-instant. Different ports avoid accidental dev-data wipes.
**Trade-offs:** Slightly more local resource usage when running tests against compose.
**Reversibility:** Easy.
**References:** docker-compose.yml; .env.test.

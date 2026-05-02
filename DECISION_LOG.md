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

### 2026-05-02 — UUID7 generation inline (no new dep)
**Phase:** 2
**Context:** `BACKEND §2` does not pin a UUID7 library. `BACKEND §7.2` mentions `uuid_extensions` and a `uuid7` package as options. Project rule: smallest possible dep set.
**Decision:** Implement `uuid7()` in `app/core/types.py` (~10 lines) per RFC 9562. 48-bit unix ms + version 7 + 12-bit rand_a + variant 0b10 + 62-bit rand_b.
**Alternatives considered:** `uuid_extensions` PyPI package; `uuid7` package; wait for Python stdlib (3.13+ has it under PEP 9). All add a dep we don't need.
**Rationale:** Algorithm is RFC-stable; tested via 4 unit tests (version, variant, monotonic ordering, ms-prefix correctness). One small function vs a transitive-dep risk and Phase 11+ ARQ-version-conflict surface.
**Trade-offs:** We own the implementation. If RFC 9562 evolves, we update one function.
**Reversibility:** Easy — swap to a library when one becomes desirable.
**References:** `app/core/types.py:uuid7`; BACKEND §7.2.

---

### 2026-05-02 — Transient `Ping` placeholder model (`app/_ping_transient.py`)
**Phase:** 2
**Context:** Phase 2 spec requires an initial migration to prove the pipeline. Alembic `--autogenerate` needs at least one model registered on `Base.metadata`. No real domain models exist until Phase 4.
**Decision:** Create `app/_ping_transient.py` with a minimal `Ping(id BIGINT PK, message VARCHAR(50))` model. Filename underscore-prefix and "transient" suffix telegraph disposability. The first Alembic revision creates the `ping` table.
**Alternatives considered:**
  - Inline the model in `migrations/env.py` — wrong layer (env.py is Alembic infrastructure).
  - Park it in `app/domain/ops/models.py` — pollutes a real bounded context.
  - Hand-write the migration without a model — defeats the autogenerate verification.
**Rationale:** A single-file, clearly-disposable placeholder is the simplest way to exercise the autogenerate → upgrade → downgrade path end-to-end.
**Trade-offs:** A second file to remove in Phase 4 (already in `BUILD_PROGRESS > Backlog`).
**Reversibility:** Trivial — delete file + write `op.drop_table("ping")` migration.
**References:** `app/_ping_transient.py`; CLAUDE_CODE_PROMPTS Phase 2.

---

### 2026-05-02 — Tests use per-test `NullPool` engine (not the module-level engine)
**Phase:** 2
**Context:** `app/core/db.py` exposes a module-level `AsyncEngine`. Pytest-asyncio creates a fresh event loop per test. Connections cached by the engine's pool become bound to whichever loop instantiated them; subsequent tests on a different loop fail with `RuntimeError: ... attached to a different loop`.
**Decision:** The `session` fixture in `tests/conftest.py` constructs its own `create_async_engine(dsn, poolclass=NullPool)` and disposes it at end-of-test. The `_ping_table_exists` helper in `test_alembic_smoke.py` follows the same pattern.
**Alternatives considered:**
  - Session-scoped event loop (`asyncio_default_fixture_loop_scope = "session"`). Fragile across pytest-asyncio versions; couples all tests to a single loop.
  - Reset the engine pool between tests. More invasive.
**Rationale:** NullPool eliminates connection caching → no cross-loop interference. Slightly slower, but tests are sub-second total.
**Trade-offs:** No connection reuse in tests; small TCP-handshake cost per test.
**Reversibility:** Easy if pytest-asyncio adds first-class support for module-engine sharing.
**References:** `tests/conftest.py:session`; `tests/integration/test_alembic_smoke.py:_ping_table_exists`.

---

### 2026-05-02 — Drive Alembic from async tests via `asyncio.to_thread`
**Phase:** 2
**Context:** `migrations/env.py` calls `asyncio.run(run_migrations_online())`. From an async test (already inside an event loop), `asyncio.run` raises `RuntimeError: asyncio.run() cannot be called from a running event loop`.
**Decision:** Async tests that need to drive `alembic.command.upgrade/downgrade` wrap the call in `await asyncio.to_thread(...)`. This delegates the sync alembic call to a worker thread that has no running loop.
**Alternatives considered:**
  - Restructure env.py to detect an existing loop and reuse it. Would require asyncio.get_event_loop fallback that's fragile across Python versions.
  - Test only via shelled-out `alembic` CLI. Slow and doesn't exercise the Python API.
**Rationale:** `asyncio.to_thread` is the canonical way to call sync code from async. Alembic's command API is sync by design.
**Trade-offs:** A tiny helper in tests (`_alembic` in `test_alembic_smoke.py`).
**Reversibility:** Trivial.
**References:** `tests/integration/test_alembic_smoke.py:_alembic`.

---

### 2026-05-02 — Removed Alembic `post_write_hooks` for ruff
**Phase:** 2
**Context:** `BACKEND §9` / typical Alembic projects post-format generated migrations. Initial config used `[post_write_hooks] hooks = ruff_format` with `type = console_scripts`. Alembic spawns a subprocess for the hook; that subprocess does NOT see our uv-managed venv's `ruff` console_scripts entry → `Could not find entrypoint console_scripts.ruff`.
**Decision:** Remove the `post_write_hooks` section from `alembic.ini`. Document that `make fmt` formats migrations along with the rest of the codebase.
**Alternatives considered:**
  - Switch to `type = exec` with `executable = uv` — works, but adds a second tool dependency for hook discovery.
  - Add `ruff` as a project-level entry point — tampering with packaging metadata for marginal gain.
**Rationale:** `make fmt` is the single source of truth for formatting; running it after `make revision` is a one-liner contractor with the existing workflow.
**Trade-offs:** Generated migrations are unformatted until `make fmt`; tolerable.
**Reversibility:** Easy.
**References:** `alembic.ini`.

---

### 2026-05-02 — Alembic `compare_type=True` + `compare_server_default=True`
**Phase:** 2
**Context:** Default Alembic `--autogenerate` ignores type widenings and server-default changes — silent drift between models and migrations.
**Decision:** Set both flags in `migrations/env.py`. Accept the noisier diffs (especially around `func.utc_timestamp(6)` rendering) as the price of catching real drift.
**Alternatives considered:** Defaults — silent drift is unacceptable per CLAUDE.md "Forced verification — before claiming complete" discipline.
**Rationale:** Catch type/default drift at autogenerate time; manually adjust the rare false-positive.
**Trade-offs:** Occasional manual migration editing to suppress benign diffs.
**Reversibility:** Easy.
**References:** `migrations/env.py`; BACKEND §9.3.

---

### 2026-05-02 — JWT ``kid`` header scaffolded; rotation deferred
**Phase:** 3
**Context:** `BACKEND §20.3` mentions 90-day JWT signing-key rotation as ops policy. Phase 3 wires the `TokenIssuer` for the first time. Implementing rotation now is premature — we'd need a key store, key registry, and orchestration.
**Decision:** Always emit `kid="k1"` in the JWT header. Decoder reads `settings.jwt_secret` directly without consulting `kid`. When rotation lands, the decoder will dispatch on `kid` to a key registry; the encoder will pick the latest active key.
**Alternatives considered:** Implement full rotation now (over-engineering); skip `kid` entirely and re-issue tokens at rotation (forces all users to re-auth simultaneously).
**Rationale:** The header field is essentially free; downstream rotation gets a clean migration path with no client changes.
**Trade-offs:** None at this scale.
**Reversibility:** Easy.
**References:** `app/core/security.py:DEFAULT_KID`; BACKEND §20.3.

---

### 2026-05-02 — Rate limiter is fixed-window (INCR + EXPIRE NX), not sliding
**Phase:** 3
**Context:** `BACKEND §18.5` describes the rate-limit pattern; PRODUCT §16 gives the limits (e.g. ``3/15m/phone``, ``10/h/IP``). Two competing implementations: fixed-window (INCR + EXPIRE NX) and sliding-window (Redis sorted-set ZADD + ZREMRANGEBYSCORE).
**Decision:** Implement fixed-window with `INCR` + `EXPIRE key window_seconds NX`. The NX flag means TTL is only set on first hit; subsequent hits don't extend the window.
**Alternatives considered:** Sliding-window via sorted set — more accurate at boundaries, ~2× memory and more Redis ops per hit. Token-bucket with `EVAL` Lua — most accurate, more complex to implement.
**Rationale:** Fixed-window is a one-pipeline-call operation; OTP burst tolerance at the boundary (briefly twice the configured rate) is acceptable for MVP. Sliding-window is a Phase 12 hardening item if measured need surfaces.
**Trade-offs:** Two windows can "stack" near a boundary. Documented in the module docstring.
**Reversibility:** Easy — swap implementation, signature unchanged.
**References:** `app/core/ratelimit.py:hit`; BACKEND §18.5.

---

### 2026-05-02 — i18n missing-key returns key + logs warning (never raises)
**Phase:** 3
**Context:** Translation lookups can miss in three ways: key absent in target lang only, key absent everywhere, or interpolation variable missing. Need a single deterministic policy that doesn't break production responses.
**Decision:**
  1. Target lang missing → fall back to ``settings.default_language`` (RU).
  2. Default lang also missing → return the literal key string + log ``i18n_missing_key`` at WARNING level.
  3. Interpolation variable missing → return the unformatted template string + log ``i18n_missing_var``.

Never raises — translation issues surface as observable log signals, not 500 responses.
**Alternatives considered:** Raise on missing key (breaks production); return empty string (silently swallows the bug); fall back to English (English isn't always translated either).
**Rationale:** Returning the key string makes the gap visible in dev/test (literal "auth.otp.title" rendered instead of Russian text); production users see a literal key, which is better than a 500. Logs catch it for ops.
**Trade-offs:** Small chance of literal-key strings reaching production users. Mitigated by tests asserting fallback behaviour and the BACKEND §27 conventions checklist for new keys.
**Reversibility:** Easy — change one branch.
**References:** `app/core/i18n.py:t`; BACKEND §22.

---

### 2026-05-02 — Idempotency state in Redis only, never MySQL
**Phase:** 3
**Context:** `BACKEND §21.3` calls for Idempotency-Key state in Redis. We could put it in the OLTP DB for durability, but that adds write traffic on the hot path of place-order.
**Decision:** Idempotency state lives in Redis under ``v1:idem:{scope}:{key}`` with 24-hour TTL. Payload is ``orjson.dumps({"digest": "...", "response": {...}})``.
**Alternatives considered:** MySQL table with TTL via cron cleanup; write-through to both.
**Rationale:** Redis is sized for this kind of short-lived high-traffic state. The OLTP DB stays lean. If Redis loses state, the worst case is a duplicate order — and order placement is already a transactional boundary that catches duplicates via stock checks.
**Trade-offs:** A Redis flush before TTL expiry could cause an unintended duplicate. Acceptable; the place-order transaction's stock invariants prevent overselling regardless.
**Reversibility:** Easy if we want durability later — add a table, dual-write, deprecate Redis path.
**References:** `app/core/idempotency.py`; BACKEND §21.3.

---

### 2026-05-02 — Cursor encoding: base64url JSON of (created_at, id)
**Phase:** 3
**Context:** Cursor pagination needs an opaque token that survives URL boundaries and can be base64-decoded back to a keyset pointer. JSON shape: ``{"created_at": ISO8601, "id": "<str>"}``.
**Decision:** ``encode_cursor(created_at, item_id)`` → ``base64.urlsafe_b64encode(orjson.dumps({...}))`` with trailing ``=`` stripped. ``decode_cursor`` re-pads, decodes, and parses. ``id`` is always stringified at encode time so callers can pass UUIDs or BIGINTs.
**Alternatives considered:** Plain integer cursor (offset) — leaks magnitude info; signed JWT cursor (overkill for opaque pagination); hex-encoded composite key — uglier.
**Rationale:** base64url is URL-safe and standard; orjson handles `datetime` cleanly; clients never inspect the cursor.
**Trade-offs:** Cursor strings are slightly longer than offset integers.
**Reversibility:** Easy — encoding is encapsulated in two functions.
**References:** `app/core/pagination.py:encode_cursor`; BACKEND §20.2.

---

### 2026-05-02 — Tests use per-test Redis init/close (not session-scoped)
**Phase:** 3
**Context:** Same pytest-asyncio function-loop / module-state mismatch as the DB engine in Phase 2. A session-scoped Redis fixture gets connections bound to the first test's loop; subsequent tests on new loops fail.
**Decision:** `redis_clean` fixture in `tests/conftest.py` does close → init → flushdb → yield → close per test. ~100ms per test cost; negligible for the 11 Redis-using tests at this scale.
**Alternatives considered:** Session-scoped fixture with `loop_scope="session"` (couples all tests to a single loop, fragile); explicit per-test re-binding (more code).
**Rationale:** Mirrors the Phase 2 NullPool decision — per-test simplicity beats session-scope perf at this scale.
**Trade-offs:** Slightly slower tests; absolutely correct semantics.
**Reversibility:** Easy.
**References:** `tests/conftest.py:redis_clean`.

---

### 2026-05-02 — `python-jose` retained for Phase 3; review at Phase 4
**Phase:** 3
**Context:** OPEN_QUESTIONS Q6 flagged `python-jose` for upstream-activity review. Phase 3 wires `TokenIssuer` for the first time — natural earlier check.
**Decision:** Keep `python-jose` for Phase 3. Defer the swap-or-stay decision to Phase 4 design (when JWT integrates with the customer auth flow). The `TokenIssuer` API is small and library-agnostic — swap cost is ~30 LoC.
**Alternatives considered:** Switch to PyJWT now (preempts a future migration); swap on first CVE (reactive).
**Rationale:** No fresh CVE evidence at the time of writing; swapping mid-Phase-3 introduces a non-feature change. Phase 4 is the right pause point.
**Trade-offs:** A CVE between now and Phase 4 forces a faster swap. Risk register R-7 tracks it.
**Reversibility:** Trivial. The `from jose import jwt` line and one decode call are the only library-specific code.
**References:** OPEN_QUESTIONS Q6; RISKS R-7; `app/core/security.py:TokenIssuer`.

---

### 2026-05-02 — `python-jose` retained at Phase 4 (resolves OPEN_QUESTIONS Q6)
**Phase:** 4
**Context:** Q6 deferred from Phase 0 / Phase 3. Phase 4 wires `TokenIssuer` for the customer flow.
**Decision:** Keep `python-jose>=3.3,<4.0`. 3.5.0 carries the historical CVE patches; the swap surface is small (~30 LoC in ``app/core/security.py``). Risk register R-7 stays open for monthly review.
**Alternatives considered:** Switch to PyJWT pre-emptively. Higher cost, no fresh CVE evidence today.
**Rationale:** Maturity of the existing implementation + small swap cost + no current vulnerability outweighs the perceived maintenance lag. If a CVE drops, swap is one PR.
**Trade-offs:** Continuing supply-chain risk, monitored.
**Reversibility:** Easy.
**References:** OPEN_QUESTIONS Q6; RISKS R-7.

---

### 2026-05-02 — Refresh token: JWT-encoded with ``jti`` in Redis (resolves Q9)
**Phase:** 4
**Context:** Q9 asked whether refresh tokens should be opaque (Redis-only) or JWT-encoded with a Redis-backed jti.
**Decision:** JWT-encoded refresh tokens with a `jti` claim. The `jti` is stored in Redis under ``v1:session:refresh:{jti}`` (TTL = refresh TTL). On refresh: decode JWT → check Redis for jti → issue new pair → delete old jti → store new jti. On logout: delete the jti.
**Alternatives considered:** Opaque refresh + DB row. JWT only (no Redis) — no revocation.
**Rationale:** JWT signature provides authenticity proof without DB hit; Redis presence is the actual revocation mechanism. Best of both: stateless verify + revocable.
**Trade-offs:** Two layers to reason about (JWT + Redis). On Redis flush, all refresh tokens become invalid (acceptable — users re-OTP).
**Reversibility:** Implementation localised in `AuthService` + `OtpService`.
**References:** `app/domain/identity/services.py`; OPEN_QUESTIONS Q9.

---

### 2026-05-02 — `user_addresses.user_id` FK uses ``ON DELETE RESTRICT`` (deviates from PHARMACY §4.2's ``CASCADE``)
**Phase:** 4
**Context:** PHARMACY §4.2 specifies ``ON DELETE CASCADE``. We need a STORED generated column (`default_user_id`) that references `user_id` to enforce the "one default address per user" UNIQUE workaround (BACKEND §6.5). MySQL forbids a STORED generated column from depending on a column whose FK uses CASCADE / SET NULL / SET DEFAULT (causes ``ERROR 1215: Cannot add foreign key constraint`` at DDL time). Empirically confirmed in Phase 4.2.
**Decision:** Use ``ON DELETE RESTRICT`` for `user_addresses.user_id`.
**Alternatives considered:** Drop the generated-column trick and enforce default-uniqueness in app code (race-prone). Use a VIRTUAL generated column (slower, doesn't help — same restriction).
**Rationale:** Users are soft-deleted (deleted_at), so RESTRICT effectively never fires; ORM-level `cascade="all, delete-orphan"` cleans up addresses before any hard delete. RESTRICT is also a defensive default — prevents accidental orphaning.
**Trade-offs:** Hard-delete of a user with addresses requires explicit cleanup (already handled by ORM cascade).
**Reversibility:** Easy if MySQL relaxes the rule.
**References:** `app/domain/identity/models.py:UserAddress`; PHARMACY §4.2; BACKEND §6.5.

---

### 2026-05-02 — `branches` table created in Phase 4 (despite Phase 6 owning inventory)
**Phase:** 4
**Context:** `admin_users.branch_id REFERENCES branches(id)`. Without `branches`, the FK fails. Phase 6 covers the rest of inventory (`branch_products`, `inventory_batches`, `stock_movements`) but the table itself is needed earlier.
**Decision:** Land the full PHARMACY §6.1 `branches` table in Phase 4's migration. Phase 6 will not redefine it.
**Alternatives considered:** Stub branches as a minimal table now and ALTER in Phase 6. More migrations, more risk.
**Rationale:** PHARMACY §13.2 migration order itself puts `branches` before `admin_users`, so we're matching the spec.
**Trade-offs:** Phase 4 carries one piece of "inventory" work.
**Reversibility:** N/A.
**References:** `migrations/versions/20260502_1631_create_identity_tables.py`; PHARMACY §6.1, §13.2.

---

### 2026-05-02 — Failed-login counter committed BEFORE raising AuthenticationError
**Phase:** 4
**Context:** `BACKEND §11/§12` rule: services don't commit; the request boundary commits via `get_db`, which rolls back on exception. But the lockout counter MUST persist across failed-login exceptions — otherwise `failed_login_count` resets on every wrong password, and the 5-attempt lockout never fires.
**Decision:** In `AdminAuthService.login_with_password`, after `increment_failed_login` (and possibly `set_locked_until`), call ``await self.admins.session.commit()`` BEFORE raising `AuthenticationError`. Then `get_db`'s exception rollback is a no-op on the now-committed session (start-then-rollback an empty transaction).
**Alternatives considered:** Use a separate session/engine for the increment (heavier; requires opening a side-channel transaction). Use SAVEPOINT (doesn't survive parent rollback). Catch the exception in the route and commit before re-raising (couples auth flow with route).
**Rationale:** The cleanest place for a security-critical side effect is in the service that knows about the security context. Documented exception to the broader "services don't commit" rule.
**Trade-offs:** A second commit-then-rollback path; tested empirically — works on MySQL InnoDB.
**Reversibility:** Easy.
**References:** `app/domain/identity/services.py:AdminAuthService.login_with_password`; BACKEND §11.3, §12.

---

### 2026-05-02 — `email-validator` added (for `pydantic.EmailStr`)
**Phase:** 4
**Context:** `pydantic.EmailStr` requires `email-validator`. Used for `users.email` and `admin_users.email`.
**Decision:** Add `email-validator>=2.2,<3.0` to runtime deps. Updated `BACKEND §2`-style pin in `pyproject.toml`.
**Alternatives considered:** Plain `str` + custom validator. More code, less robust.
**Rationale:** Small, well-maintained package; standard pydantic idiom.
**Reversibility:** Easy.
**References:** `pyproject.toml`; OPEN_QUESTIONS no item.

---

### 2026-05-02 — TOTP MFA enforcement deferred from Phase 4
**Phase:** 4
**Context:** PRODUCT §19.3: "For MVP, MFA optional." `admin_users.mfa_secret` column exists; Phase 4 admin login does NOT verify TOTP codes when `mfa_secret` is set.
**Decision:** Phase 4 is email + password only. The `mfa_secret` column is preserved; if it's set, a warning logs but the verify is bypassed. A future phase (Phase 1.5+) adds `pyotp` and the verification path.
**Alternatives considered:** Add `pyotp` now and verify when `mfa_secret` is set. Adds a dep without enrolment UX.
**Rationale:** Spec explicitly defers; avoiding `pyotp` keeps the dep set tight per project rule "smallest possible package."
**Trade-offs:** A prematurely-set `mfa_secret` doesn't enforce until later phase.
**Reversibility:** Easy.
**References:** `app/domain/identity/services.py:AdminAuthService`; PRODUCT §19.3.

---

### 2026-05-02 — E2E `client` fixture overrides `get_db` with NullPool engine
**Phase:** 4
**Context:** Same root cause as Phases 2/3 — pytest-asyncio function-scoped event loops collide with module-level pooled connections. The route handler uses `app.core.db.engine` via `get_db`; the second test on a new loop hits "Future attached to a different loop" inside Starlette middleware.
**Decision:** `tests/conftest.py:client` fixture builds a fresh `create_async_engine(..., poolclass=NullPool)` per test, wraps it in an `async_sessionmaker`, and registers it as a `dependency_override` for `get_db`. Disposes at fixture teardown.
**Alternatives considered:** Session-scoped event loop (fragile across versions); manual lifespan invocation (`asgi-lifespan` LifespanManager — adds complexity).
**Rationale:** Mirrors the existing per-test NullPool pattern from Phase 2/3 (`session` fixture and `redis_clean`). Consistent project-wide test posture.
**Trade-offs:** Each E2E request opens a fresh DB connection. Negligible at this scale.
**Reversibility:** Easy.
**References:** `tests/conftest.py:client`.

---

### 2026-05-02 — Pydantic validation errors strip `ctx.error` for orjson serialisation
**Phase:** 4
**Context:** When a `field_validator` raises `ValueError`, pydantic stores the exception in `ctx.error`. `RequestValidationError.errors()` returns this Exception object as-is. `orjson.dumps` can't serialise Exception → 500 error in our handler.
**Decision:** In `app/api/errors.py:_validation`, strip `ctx` and `url` keys, stringify any remaining `ctx` dict values defensively, before passing to `_problem`.
**Alternatives considered:** Use `pydantic.ValidationError.errors(include_context=False)` — works only on `ValidationError`, not the FastAPI subclass. Custom `default=` for orjson — more invasive.
**Rationale:** Two-line fix in the handler. Errors stay informative (still shows `loc`, `msg`, `type`) without leaking exception objects.
**Reversibility:** Easy.
**References:** `app/api/errors.py:register_exception_handlers`.

---

### 2026-05-02 — `ensure_utc(dt)` helper for naive-vs-aware datetime comparisons
**Phase:** 4
**Context:** MySQL `DATETIME(fsp=6)` reads come back tz-naive. Our `utcnow()` is tz-aware. Comparing the two raises `TypeError: can't compare offset-naive and offset-aware datetimes`. Bit us in `AdminAuthService.login_with_password` checking `admin.locked_until > utcnow()`.
**Decision:** Added `ensure_utc(dt)` to `app/core/time.py` — attaches UTC tzinfo if naive, returns as-is if already aware. Use this for any Python-level datetime comparison against `utcnow()`.
**Alternatives considered:** Switch all `utcnow()` to naive UTC (project-wide convention shift). Use a SQLAlchemy type adapter that attaches UTC on read (more invasive).
**Rationale:** Smallest possible fix; makes the convention explicit at use sites.
**Trade-offs:** Need to remember to call `ensure_utc` whenever comparing DB-read datetimes against `utcnow()`. Caught at runtime if forgotten.
**Reversibility:** Easy.
**References:** `app/core/time.py:ensure_utc`.

---

### 2026-05-02 — `admin_audit_log` table created in Phase 5 (relocated from Phase 9)
**Phase:** 5
**Context:** PHARMACY §8.1 originally puts `admin_audit_log` in the ops domain (Phase 9). But every catalog/inventory/order admin mutation needs to write an audit row from day one — without the table, mutations have nowhere to log.
**Decision:** Land `admin_audit_log` in Phase 5's migration alongside the catalog tables. Phase 9 will add only the read-side viewer endpoint (`F-ADM-AUD-001`).
**Alternatives considered:** Buffer audit events to a queue/log file in Phase 5 and replay them when the table arrives in Phase 9. Adds operational complexity and a window where audit data is at risk.
**Rationale:** CLAUDE_CODE_PROMPTS Phase 5 explicitly recommends this. One migration > buffer + replay.
**Trade-offs:** Phase 9 owns the entity but Phase 5 owns the schema. Documented.
**Reversibility:** N/A.
**References:** `migrations/versions/20260502_1724_create_catalog_and_audit_log.py`; CLAUDE_CODE_PROMPTS Phase 5.

---

### 2026-05-02 — `python-slugify[unidecode]` for Cyrillic → Latin URL slugs
**Phase:** 5
**Context:** Categories, symptoms, and products need URL slugs. Russian product names (`Панадол 500мг`) need transliteration; the spec PHARMACY §5.6 has no transliteration logic and `BACKEND §2` doesn't pin a slug library.
**Decision:** Add `python-slugify[unidecode]>=8.0,<9.0` to runtime deps. Implement `slugify_name(name)` in `app/domain/catalog/slug.py`.
**Alternatives considered:** Hand-roll a GOST 7.79 transliteration map (~100 LoC, error-prone). Use `unidecode` directly (no slug post-processing). Use `awesome-slugify` (less maintained).
**Rationale:** `python-slugify` is the de facto standard, has the `unidecode` extra for non-ASCII, and is small + actively maintained. Verified output: `Панадол 500мг → panadol-500mg`, `Парацетамол → paratsetamol`, `Аптека на Чуй → apteka-na-chui`.
**Trade-offs:** Adds two transitive deps (`python-slugify`, `unidecode`). Acceptable for the value.
**Reversibility:** Easy.
**References:** `app/domain/catalog/slug.py`; `pyproject.toml`.

---

### 2026-05-02 — Bulk import: CSV only at Phase 5; XLSX deferred to Phase 1.5+
**Phase:** 5
**Context:** F-ADM-CAT-002 specifies "CSV or XLSX up to 10 MB". XLSX requires `openpyxl` (~2 MB transitively).
**Decision:** Phase 5 ships CSV only via Python's stdlib `csv` module. The route signals `415 Unsupported Media Type` if a `.xlsx` upload is attempted. XLSX support added in Phase 1.5+ when needed; document in `BUILD_PROGRESS > Backlog`.
**Alternatives considered:** Add `openpyxl` now. `pandas` (heavy + numpy + transitive deps).
**Rationale:** CSV covers 90% of admin import workflows at MVP scale. Deferring keeps the dep set tight per project rule "smallest possible package."
**Trade-offs:** A pharmacy ops team wanting Excel upload has to convert to CSV. Acceptable for MVP.
**Reversibility:** Easy.
**References:** `app/domain/catalog/import_service.py` (Phase 5.5); BUILD_PROGRESS Backlog.

---

### 2026-05-02 — `categories` self-parent CHECK omitted (MySQL 8.0+ rejects CHECK on AUTO_INCREMENT)
**Phase:** 5
**Context:** PHARMACY §5.1 has `CHECK (parent_id IS NULL OR parent_id <> id)`. MySQL 8.0+ raises error 3818: "Check constraint cannot refer to an auto-increment column."
**Decision:** Drop the constraint from the model + migration. Enforce self-parent prevention in the service layer (`CategoryService.update_parent`).
**Alternatives considered:** Use a non-AUTO_INCREMENT PK (UUID). Rebuild via trigger (heavier, less portable).
**Rationale:** MySQL restriction is non-negotiable. Service-level enforcement is acceptable since admin mutations all go through the service.
**Trade-offs:** Lost defense-in-depth at the DB level — bypassing the service (e.g., direct SQL) could create cycles. Mitigation: BACKEND §27 conventions checklist requires service-level mutations.
**Reversibility:** N/A while on MySQL 8.x.
**References:** `app/domain/catalog/models.py:Category`; PHARMACY §5.1.

---

### 2026-05-02 — `dosage_unit` CHECK emitted via `op.execute` (avoids `%%` paramstyle escape)
**Phase:** 5
**Context:** `dosage_unit IN ('mg','g','mcg','ml','IU','%')` — the `%` value triggered SQLAlchemy's auto-doubling for paramstyle safety, emitting `'%%'` in the DDL. MySQL would have stored the literal `%%` in the constraint and rejected runtime inserts of `%`.
**Decision:** Drop the autogen `sa.CheckConstraint` from `product_active_ingredients` and emit the constraint via `op.execute("ALTER TABLE ... ADD CONSTRAINT ... CHECK (dosage_unit IN ('mg','g','mcg','ml','IU','%'))")` after table creation. Verified: insertion with `'%'` succeeds; insertion with `'BOGUS'` raises constraint error.
**Alternatives considered:** Change the enum value (e.g., `'PCT'` instead of `'%'`) — diverges from PHARMACY §5.9; user-facing display would need post-processing.
**Rationale:** Match the spec value; bypass the format-string escape with a raw DDL emit.
**Trade-offs:** A few extra lines in the migration.
**Reversibility:** Easy.
**References:** `migrations/versions/20260502_1724_create_catalog_and_audit_log.py`.

---

### 2026-05-02 — FULLTEXT `WITH PARSER ngram` via `op.execute` (SQLAlchemy can't render it)
**Phase:** 5
**Context:** `product_translations` needs a FULLTEXT index with the ngram parser for Cyrillic search (BACKEND §6.4, RISKS R-4). SQLAlchemy's `Index(..., mysql_prefix="FULLTEXT")` emits `CREATE FULLTEXT INDEX ...` but has no API for the `WITH PARSER ngram` clause.
**Decision:** In the migration, drop the autogen FULLTEXT index entry and emit it as raw SQL: `op.execute("CREATE FULLTEXT INDEX ftx_pt_search ON product_translations (name, short_description, description) WITH PARSER ngram")`. `ngram_token_size=2` is set on the server (docker-compose).
**Alternatives considered:** Skip the parser clause and use the default parser — fails on Cyrillic. Use Meilisearch from day one — Phase 12 graduation per RISKS R-4.
**Rationale:** Required for Cyrillic FTS at MVP. Verified: `SHOW INDEX FROM product_translations WHERE Key_name='ftx_pt_search'` shows `Index_type: FULLTEXT`.
**Trade-offs:** Migration carries a raw-SQL section.
**Reversibility:** `DROP INDEX ftx_pt_search ON product_translations`.
**References:** `migrations/versions/20260502_1724_create_catalog_and_audit_log.py`; BACKEND §6.4.

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


---

### 2026-05-02 — `ProductRead.symptom_ids` via `model_validator(mode="before")`
**Phase:** 5
**Context:** `Product.symptoms` is a list of `ProductSymptom` join rows; the API response shape is a flat `symptom_ids: list[int]`. With `from_attributes=True`, Pydantic looks for an attribute literally named `symptom_ids` on the ORM object — which does not exist.
**Decision:** Add a `model_validator(mode="before")` on `ProductRead` that, when given an ORM `Product`, returns a dict with `symptom_ids` projected from `value.symptoms` plus straight pass-through of the other fields. Routes can keep calling `ProductRead.model_validate(product)` without a custom converter.
**Alternatives considered:** Add a `@property symptom_ids` to the `Product` model (simpler but couples ORM to API shape). Build a dict in each route handler (verbose; duplicated).
**Rationale:** Keeps the projection in one place (the response schema). No model change needed.
**Trade-offs:** Validator's allow-list of fields must be kept in sync with `ProductRead` (acceptable; same file).
**Reversibility:** Trivial.
**References:** `app/domain/catalog/schemas.py:ProductRead`.

---

### 2026-05-02 — Catalog routes reload with translations after service mutation
**Phase:** 5
**Context:** Catalog ORM models declare `lazy="raise"` on collections (forces explicit eager loading). After `repository.add(...)` calls `session.refresh(...)`, in-memory translations populated by the service are wiped, and serialising the response via `ActiveIngredientRead.model_validate(ai)` raises `InvalidRequestError: 'translations' is not available due to lazy='raise'`.
**Decision:** Mirror the products-route pattern: after every `service.create_X` / `update_X`, the route calls `repo.get_by_id_with_translations(id)` (or `get_by_id_with_full` for products) before validating the response model. The service stays unchanged (it returns the bare ORM object).
**Alternatives considered:** Refresh inside the service with `selectinload(...)` (couples the service to one specific eager-load shape). Switch the relationship to `lazy="selectin"` (eager-loads on every query — ditches the explicit-loading discipline).
**Rationale:** Routes already control the response shape, so they're the right place to control how the response is loaded. Services stay shape-agnostic.
**Trade-offs:** One extra `SELECT` per write. Acceptable for admin paths.
**Reversibility:** Easy.
**References:** `app/api/admin_v1/{active_ingredients,categories,symptoms}.py`.

---

### 2026-05-02 — FULLTEXT smoke test asserts metadata, not live MATCH
**Phase:** 5
**Context:** A live `MATCH ... AGAINST` query on `product_translations` requires committed rows (FULLTEXT index visibility). Committing inside the per-test `session` fixture would leak rows past the rollback boundary and contaminate other tests.
**Decision:** `tests/integration/test_fulltext.py` queries `INFORMATION_SCHEMA.STATISTICS` for the `ftx_pt_search` index and parses `SHOW CREATE TABLE` output for the `WITH PARSER ngram` clause. Phase 7 will add a live MATCH suite seeded from a real fixture pool.
**Alternatives considered:** Manage a separate non-rolled-back session for FT tests (complex). Run live MATCH and rely on per-session migration teardown to clean up (fragile under parallelism).
**Rationale:** Smoke confidence at low cost. The behavioural test belongs in the search phase.
**Trade-offs:** No end-to-end coverage of the parser/score yet.
**Reversibility:** Replace with a live test in Phase 7.
**References:** `tests/integration/test_fulltext.py`; `migrations/versions/20260502_1724_create_catalog_and_audit_log.py`.

---

### 2026-05-02 — `inventory_batches.quantity_reserved` (per-batch reservation tracking)
**Phase:** 6
**Context:** PRODUCT §10.1 says "available = total - reserved". PHARMACY §11.4 SQL says `UPDATE inventory_batches SET quantity_remaining = quantity_remaining - $consumed` on reserve. CLAUDE.md "Reservation lifecycle" says reserve increments `reserved_quantity` only and `total_quantity` decrements at the sold transition. These three disagree, and *none* of them prevents oversell-of-a-single-batch under concurrent reservers without per-batch reservation tracking.

Concretely: with two batches A (100) and B (50) and ``bp.reserved=80`` from prior orders distributed somewhere between A and B, a new reserve of 30 cannot safely pick from A without knowing how much of A is already reserved. ``bp.reserved_quantity`` only captures the per-product aggregate.

**Decision:** Add ``quantity_reserved INT`` to ``inventory_batches`` with two CHECK constraints (``>= 0``, ``<= quantity_remaining``). Stock-truth model:

* ``batch.quantity_remaining`` = total physical on hand (held + free).
* ``batch.quantity_reserved`` = held by pending/confirmed/preparing orders.
* ``batch.available_to_allocate`` = ``quantity_remaining - quantity_reserved``.
* ``bp.total_quantity`` = SUM(``quantity_remaining`` for non-expired batches with expiry > today + 7 days).
* ``bp.reserved_quantity`` = SUM(``quantity_reserved``).

Side effects:
* FEFO query filters ``quantity_remaining > quantity_reserved`` (instead of ``> 0``).
* On **reserve**: ``batch.quantity_reserved += take``; ``bp.reserved_quantity += total``. ``quantity_remaining`` unchanged.
* On **sold** (preparing → ready): ``batch.quantity_remaining -= take``; ``batch.quantity_reserved -= take``; both bp aggregates decrement.
* On **released** (cancel pre-dispatch): ``batch.quantity_reserved -= take``; ``bp.reserved_quantity -= take``. Physical untouched.
* On **damaged / adjusted**: cannot reduce ``quantity_remaining`` below ``quantity_reserved`` (held stock can't be written off until releases happen).

**Alternatives considered:** Decrement ``quantity_remaining`` on reserve (per §11.4 SQL) — but then "available = total - reserved" double-counts after every reserve. Aggregate-only ``bp.reserved_quantity`` — admits oversell-per-batch under concurrency.

**Rationale:** Per-batch tracking is the only model that (a) makes the concurrent FEFO test pass without flakes; (b) keeps ``bp.total_quantity`` as the genuine cache of ``SUM(quantity_remaining for non-expired)``; and (c) lets ``available = total - reserved`` reflect reality. The concurrent-FEFO test (`tests/integration/test_fefo_concurrent.py`) verifies the model holds under contention.

**Trade-offs:** One extra column + two extra CHECKs. Adjustments must consider held stock (small admin UX implication; documented in service errors).

**Reversibility:** Easy — column is additive; reverting would require reverting the service logic, not the schema.

**References:** `app/domain/inventory/models.py:InventoryBatch`; `app/domain/inventory/services.py:InventoryService.reserve`; `tests/integration/test_fefo_concurrent.py`; PRODUCT §10.1; PHARMACY §6.4, §11.4.

---

### 2026-05-02 — `branch_products` auto-created on first receive at price=0, is_available=False
**Phase:** 6
**Context:** A receive can hit a `(branch, product)` that has never been priced. Two options: (a) lazy-create the row at `price=0, is_available=False` with a "pending pricing" flag; (b) require an explicit "list product at branch" admin action before any receive succeeds. Phase 6 prompt §6 leans toward (a).

**Decision:** Lazy-create on first receive. ``BatchReceiveResponse`` carries ``branch_product_pending_pricing: bool`` so the admin UI can flag the next-step prompt ("set a price"). Storefront filtering is on ``is_available=true``, so these rows are invisible to customers until admin prices them.

**Alternatives considered:** Require an explicit list-at-branch step — bureaucratic; receiving is the natural first interaction with a product at a branch.

**Rationale:** Pragmatic. Prevents the receive workflow from blocking on a separate admin step. Storefront safety preserved by ``is_available=False`` default.

**Trade-offs:** Possible to forget pricing and have stock physically present but invisible. Mitigated by the response flag and an obvious low-stock-style admin alert (Phase 9 dashboards).

**Reversibility:** Easy — change the service to raise instead of auto-create.

**References:** `app/domain/inventory/services.py:InventoryService.receive_batch`.

---

### 2026-05-02 — `stock_movements.order_id` is column-only at Phase 6 (FK in Phase 8)
**Phase:** 6
**Context:** ``stock_movements`` references the future ``orders`` table by id. Orders don't exist until Phase 8; we need ``stock_movements`` now for receive / adjust audit.

**Decision:** Define ``order_id`` as a nullable ``BINARY(16)`` (``GUID``) column without a foreign key in Phase 6's migration. Phase 8's migration adds ``ALTER TABLE stock_movements ADD CONSTRAINT fk_sm_order FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE SET NULL`` once the orders table lands.

**Alternatives considered:** Forward-declare an orders stub in Phase 6 — adds noise; tested and rejected. Use ``CHAR(36)`` to dodge GUID — abandons the byte-swapped UUID7 layout.

**Rationale:** Column shape is correct now; FK can be added later without data migration.

**Trade-offs:** A reserved/sold movement could in theory reference a non-existent ``order_id`` until Phase 8 ships. The application layer always sets ``order_id`` from a freshly-issued ``uuid7()``, so the risk is theoretical.

**Reversibility:** Trivial — the FK is the only thing missing.

**References:** `migrations/versions/20260502_1827_create_inventory_tables.py`; `app/domain/inventory/models.py:StockMovement`.

---

### 2026-05-02 — Admin UI copy is EN-primary at MVP; PRODUCT §21 covers customer copy only
**Phase:** 6
**Context:** PRODUCT §21 enumerates customer-facing strings in RU/KY/EN. Admin-tier strings (receiving form labels, adjustment reasons, validation errors) are not catalogued. Russian admin would need a separate i18n pass.

**Decision:** Admin endpoints return error codes (``code: "expiry_within_hard_block"``); admin frontend resolves the message in EN at MVP. Phase 9 (the audit-log viewer + reports) is the natural revisit point if the team wants RU admin UI.

**Rationale:** Backend stays code-first; no premature i18n investment for a tiny internal audience.

**Trade-offs:** Bishkek pharmacists are RU-primary; if they prefer RU, frontend ships an admin RU bundle later. Backend doesn't need to change.

**Reversibility:** Easy — admin codes are stable; FE can map them to any locale.

**References:** `app/api/admin_v1/inventory.py` (no `t()` lookups).

---

### 2026-05-02 — Concurrent FEFO test runs 50× by default, parameterised to 100× via `FEFO_CONCURRENT_LOOPS`
**Phase:** 6
**Context:** Phase 6 prompt asks for the concurrent FEFO test to run 100× in CI to catch flakes. 100× per-loop set-up + teardown adds ~3-4s to the test suite, which compounds across other repeated tests.

**Decision:** Default to **50 loops** (`tests/integration/test_fefo_concurrent.py`); honour `FEFO_CONCURRENT_LOOPS` env override. Nightly CI sets it to 100; PR runs at 50. Each loop seeds a fresh `(branch, product, batches)` triple, so loops are fully independent.

**Rationale:** 50 catches concurrency bugs reliably (validated locally); 100 buys marginal additional confidence at the cost of doubling the run time. Nightly runs at 100 keep the spec target.

**Trade-offs:** Slightly less concurrency confidence on PR. If a regression slips through 50× and only fails at 100×, nightly catches it within 24h.

**Reversibility:** Trivial — change the env default.

**References:** `tests/integration/test_fefo_concurrent.py`.

---

### 2026-05-02 — Composing `require_role` + `require_branch_access`: nested-Depends factory, not stacked `Annotated`
**Phase:** 6
**Context:** Routes that need both role-gating and per-branch-scoping for non-super-admins. Obvious form `Annotated[AdminUser, Depends(require_role(...)), Depends(require_branch_access(...))]` silently fires only the last `Depends` — FastAPI binds the variable from the rightmost provider and ignores earlier ones in the same `Annotated`. Discovered the bug because `content_editor` (which lacks role permission) was being admitted to inventory routes.

**Decision:** Wrap both checks in a single inner factory. `app/api/admin_v1/inventory.py:_branch_admin(*roles)` returns a nested dep whose own parameters bind to `Depends(require_role(*roles))` and `Depends(require_branch_access('branch_id'))`, then returns the role-gated admin. Both deps run; both raise on mismatch. Used `param: T = Depends(...)` (not `Annotated[T, Depends(...)]`) inside the closure because `from __future__ import annotations` defers annotations to strings, and the closure-captured `role_check` / `branch_check` aren't resolvable by `get_type_hints` at module level.

**Rationale:** Idiomatic FastAPI composition. The bug is not obvious from code review and silently downgrades RBAC — must not recur.

**Trade-offs:** Slightly more indirection. Worth it.

**Reversibility:** Trivial.

**References:** `app/api/admin_v1/inventory.py:_branch_admin`.

---

### 2026-05-02 — Composite search ranking weights (exact 1000, prefix 500, FULLTEXT × 10, ingredient 50, symptom 30, manufacturer 20)
**Phase:** 7
**Context:** PRODUCT §12.2 lists six tiers of search match quality but doesn't specify weights. Without concrete weights, every future change to search ranking is a re-derivation.

**Decision:** Lock the weights in `app/domain/catalog/repositories.py:storefront_search`:

* exact name match            → **1000**
* name prefix                 → **500**
* FULLTEXT MATCH score × 10
* active ingredient match     → **50**
* symptom-tag match           → **30**
* manufacturer match          → **20**

Computed as a single SQL `CASE` expression in the SELECT, ordered by `score DESC, is_featured DESC, created_at DESC`, filtered by `HAVING score > 0`.

**Alternatives considered:** Tuned via Bayesian optimisation against zero-result logs (premature for MVP). Per-language weights (one set; can split later if `synonyms_used` analytics shows EN behaving differently).

**Rationale:** Exact > prefix > fuzzy is the spec ordering. Multiplicative gaps (1000/500/10) ensure exact wins even when FULLTEXT fires high. The bonuses (50/30/20) only matter when name match is weak — they tie-break.

**Trade-offs:** A pathological FULLTEXT score above ~50 could promote a fuzzy-match above an ingredient-only match. Acceptable: in practice MATCH scores cluster ≤ 5.

**Reversibility:** Trivial — change the constants in the SELECT.

**References:** `app/domain/catalog/repositories.py:_storefront_search`; PRODUCT §12.2; `tests/unit/test_search_quality.py`.

---

### 2026-05-02 — Synonyms in `app/i18n/synonyms_ru.json`, application-side expansion
**Phase:** 7
**Context:** PRODUCT §12.4 examples (`анальгин ↔ метамизол`, `от головы → головная боль обезболивающее`, etc.). The dictionary needs to be admin-maintainable but Phase 9's admin UI doesn't exist yet.

**Decision:** Phase 7 ships the dictionary as a checked-in JSON file at `app/i18n/synonyms_ru.json`. `SearchService` loads it once at module import and OR-expands matched query tokens / phrases as additional terms in the boolean MATCH query. The `_doc` / `_xxx` keys are documentation-only and stripped at load time. Phase 9 adds an admin-managed table + invalidation; Phase 7 takes the simpler path.

**Alternatives considered:** Index-time synonym expansion via MySQL stopwords/synonyms file (ngram parser doesn't support synonym dictionaries). Two-stage rewriter that runs Levenshtein on misses (deferred — RISK R-4 escalates to Meilisearch).

**Rationale:** File-based is the smallest thing that works. Application-side expansion is testable, debuggable, and easy to extend.

**Trade-offs:** Editing requires a redeploy. Small dictionary keeps the in-process load cost trivial.

**Reversibility:** Easy — Phase 9 will move it to DB without changing the SearchService API.

**References:** `app/i18n/synonyms_ru.json`; `app/domain/catalog/search.py:_load_synonyms`.

---

### 2026-05-02 — Storefront branch resolver hardcoded to `branch_id=1`
**Phase:** 7
**Context:** Multi-branch UX (branch picker on the storefront) is Phase 2 of the product roadmap. MVP runs single-branch (Bishkek Central). The customer-facing storefront still needs *some* branch_id resolution to query stock + price.

**Decision:** `app/api/deps.py:get_storefront_branch_id` returns the constant `1` and is exposed as `BranchIdDep`. All storefront route handlers pin against this. Phase 2 swaps the body for header / cookie / query-param resolution. The seed scripts give the first branch id=1.

**Alternatives considered:** Read from a `Cookie: branch_id=N`. Adds protocol surface area before the picker exists.

**Rationale:** The seam is what matters; the dep makes the swap a one-liner.

**Trade-offs:** E2E tests need their seeded `branch_products` rows pinned to `branch_id=1`. Documented inline in `tests/e2e/test_storefront_endpoints.py:_seed_full_storefront`.

**Reversibility:** Trivial.

**References:** `app/api/deps.py:get_storefront_branch_id`.

---

### 2026-05-02 — Cache invalidation is best-effort (no-op when Redis is missing)
**Phase:** 7
**Context:** `CatalogAdminService` / `ProductService` / `InventoryService.update_branch_product` call `cache.invalidate("v1:cat:tree:")` etc. on every mutation. Unit tests that exercise these services without spinning up Redis would crash at the `get_redis()` call.

**Decision:** `app/core/cache.py:invalidate` catches `RuntimeError` from `get_redis()` and returns `0`. Failures to invalidate must not break a write path — the cache is a perf optimisation, and the short TTLs (≤ 1h) self-heal any drift within their window.

**Alternatives considered:** Initialise Redis in every unit test that touches a service that mutates. Adds 100ms × ~50 tests = 5s to the suite for no benefit. A test-only `NoOpCache` injected via DI — would require wiring through repo/service constructors.

**Rationale:** Smallest change, biggest test-suite ergonomics win. Production behaviour unaffected (Redis is initialised at app startup and stays up).

**Trade-offs:** A crashed Redis in production silently degrades cache invalidation. Mitigation: TTL self-heals; Sentry will already report the original Redis error.

**Reversibility:** Trivial — flip the try/except to `raise`.

**References:** `app/core/cache.py:invalidate`.

---

### 2026-05-02 — `BINARY(16)` byte-swap helpers for raw `text()` storefront queries
**Phase:** 7
**Context:** The storefront list / search / substitutes methods use `text()` for FULLTEXT MATCH + composite-ranked CASE expressions (FULLTEXT scoring isn't expressible in SQLAlchemy ORM). The `GUID` `TypeDecorator` (`app/core/types.py`) byte-swaps `UUID ↔ BINARY(16)` only on ORM/Core column ops — `text()` parameters and result rows bypass it.

Symptoms: substitutes excluded the source product's id but matched it (wrong-direction byte swap on bind); search results' `product_id` came back byte-swapped (decoded as if the bytes were already the original layout, producing a different UUID).

**Decision:** Add `_guid_bind(UUID) -> bytes` and `_guid_load(bytes | UUID) -> UUID` helpers (`app/domain/catalog/repositories.py`) that mirror `GUID.process_bind_param` / `process_result_value`. Storefront `text()` queries call them on every UUID parameter and every UUID column read.

**Alternatives considered:** Use `UUID_TO_BIN(:p, 1)` / `BIN_TO_UUID(:c, 1)` in the SQL — ties us to MySQL's exact UDF surface. Pure-ORM rewrite — gives up FULLTEXT scoring expressibility.

**Rationale:** Keeps the byte-swap logic in one place across both the column-bound and the raw-text paths.

**Trade-offs:** Two small helpers + a discipline ("call them whenever touching `BINARY(16)` in `text()`"). Test coverage on substitutes / search exercises this end-to-end.

**Reversibility:** Trivial.

**References:** `app/domain/catalog/repositories.py:_guid_bind`, `_guid_load`.

---

### 2026-05-02 — One `order_item` per allocation, not per cart line
**Phase:** 8
**Context:** A single cart line for product P with quantity 10 may FEFO-split across two batches (e.g. 6 from batch A, 4 from batch B). Two natural shapes: (a) one `order_item` per cart line, with `inventory_batch_id` left blank if multi-batch; (b) one `order_item` per allocation slice — same product, same line, but a row per batch.

**Decision:** Shape (b) — **one `order_item` per allocation**. A 2-batch split produces 2 rows on the order, each snapshotting its own `batch_number` + `expiry_date` + per-batch quantity. Cart-line totals are reconstructable by grouping `order_items` by `product_id`.

**Rationale:** PRODUCT §10.7 (recall handling) needs per-batch traceability — which customers received batch X. Snapshot integrity per batch is the cleanest way to deliver that without a side table. Shape (a) would have required an `order_item_batches` join table to record allocations.

**Trade-offs:** UI rendering needs a group-by step on `product_id`. Cosmetic; the API can pre-group when convenient.

**Reversibility:** Hard once orders exist — but the data shape is cumulative; we'd never need to switch back.

**References:** `app/domain/orders/checkout_service.py:place_order` (step 7); PRODUCT §10.7.

---

### 2026-05-02 — `order_number` via per-year `order_sequences` row + `SELECT … FOR UPDATE`
**Phase:** 8
**Context:** Customer-facing identifier needs to be human-readable (`PH-YYYY-NNNNNN`), unique, monotonic per year, and atomic under concurrent place-orders. MySQL's `AUTO_INCREMENT` doesn't restart per year; UUIDs aren't readable; per-year `AUTO_INCREMENT` tables churn schema annually.

**Decision:** Single `order_sequences(year INT PK, last_assigned BIGINT)` table. `OrderSequenceRepository.next_for_year(year)` does `SELECT … WHERE year = ? FOR UPDATE`, lazily inserts the row at `0` for a fresh year, increments, returns the new value. Format: `PH-{year}-{value:06d}`. The whole thing runs inside the place-order transaction so the increment is part of the atomic write.

**Alternatives considered:** (a) Annual `orders_2026 / orders_2027` partition tables — operational nightmare. (b) Hash-of-uuid7 truncated to 6 digits — not monotonic, possible collisions. (c) MySQL sequences via stored procedure — committee vibe.

**Rationale:** Smallest-thing-that-works. The row lock serializes concurrent place-orders **on the sequence only** — by the time the lock is grabbed, the FEFO + reserve work is done; the lock window is microseconds.

**Trade-offs:** All concurrent place-orders within the same year serialize on this single row. At Bishkek-pharmacy traffic (≤ a few QPS) this is fine. At hyperscale, sharded sequences would replace this without changing the public format.

**Reversibility:** Trivial.

**References:** `app/domain/orders/repositories.py:OrderSequenceRepository`; `app/domain/orders/models.py:OrderSequence`; PRODUCT-spec format requirement.

---

### 2026-05-02 — REPEATABLE READ + per-row `FOR UPDATE` is sufficient; no SERIALIZABLE
**Phase:** 8
**Context:** MySQL InnoDB defaults to REPEATABLE READ. Concerns: phantom reads on stock; price snapshots updating between cart-load and place-order; race between two devices placing the same cart.

**Decision:** Stay on REPEATABLE READ. The place-order transaction takes targeted row locks: `branch_products` via `with_for_update()` (`get_for_update`), inventory_batches via `FOR UPDATE SKIP LOCKED` (Phase 6 `list_for_fefo_locked`), and `order_sequences` via `FOR UPDATE` for the order-number bump. SQLAlchemy's session-level autoflush ensures writes are visible to subsequent SELECTs in the same transaction. SERIALIZABLE would force gap locks across the board with a measurable throughput cost.

**Verification:** `tests/integration/test_order_concurrency.py::test_two_orders_two_batches_partial_allocation` runs `asyncio.gather` of two place-orders against the same `(branch, product)` and asserts no oversell, no double-spend per batch, and exactly the expected reservation deltas — 30 loops by default, 50 in nightly.

**Alternatives considered:** SERIALIZABLE for `place_order` only — saves nothing; row locks already cover the invariants. Optimistic locking via version columns — adds bookkeeping for a problem we don't have.

**Trade-offs:** Future SQL changes that break the locking discipline could re-introduce races; the test suite is the safety net.

**Reversibility:** Trivial — flip an isolation pragma if needed.

**References:** `app/domain/orders/checkout_service.py:place_order`; `tests/integration/test_order_concurrency.py`; PHARMACY §11.4.

---

### 2026-05-02 — Idempotency uses `app.core.idempotency` directly in the route, not a global middleware
**Phase:** 8
**Context:** Phase 3 shipped a Redis-backed idempotency helper (`check`, `store`, `body_digest`). Place-order needs the header `Idempotency-Key`; future admin endpoints (refund, bulk import) will too. Two integration shapes: (a) global middleware that intercepts every POST; (b) per-route inline call.

**Decision:** Per-route inline call. The route reads `Idempotency-Key` (required — `ValidationError 400 idempotency_key_required` if absent), computes `body_digest(orjson.dumps(payload.model_dump(mode="json")))`, calls `idem.check` → `hit_same` returns the cached response, `hit_different` returns 409 `idempotency_conflict`, `miss` proceeds and `idem.store`s on success.

**Rationale:** Only `POST /checkout/place`, `POST /admin/orders/.../refund` (Phase 9), and `POST /admin/products/import/apply` (Phase 5 — already shipped without it; could be retrofitted) need this. A global middleware adds blast radius (everything has to opt out) without a payoff. Inline call is auditable and doesn't surprise readers.

**Alternatives considered:** Middleware with an allow-list — added indirection. Generic dependency that returns the cached response — couples request shape to dep machinery.

**Trade-offs:** Each endpoint that adopts this needs ~10 lines of boilerplate. Acceptable.

**Reversibility:** Easy.

**References:** `app/api/v1/checkout.py:place_order`; `app/core/idempotency.py`; BACKEND §21.

---

### 2026-05-02 — Cart writes allowed for guests via `pharmacy_cart_session` cookie; merge runs on login
**Phase:** 8
**Context:** PRODUCT J-01 (Bekzat — first-time symptom shopper) requires cart-write before any auth challenge. The auth wall is at "Place order", not "Add to cart". Implementation: a guest-session cookie identifies the cart for unauthenticated users; on successful login, the guest cart is merged into the user's cart.

**Decision:** Cookie name `pharmacy_cart_session`, HttpOnly, SameSite=Lax, 30-day TTL, `secure=True` when the request scheme is HTTPS. The `CartOwner` dep resolves `(user_or_None, session_id_or_None)` — logged-in users always win (their cart is keyed by `user_id`). The `_ensure_session_cookie` helper mints a session id on first guest GET. `CartService.merge_guest_into_user(user, session_id)` is the merge entry point — Phase 8 ships the method; the auth-flow hook (call from `AuthService.verify_otp` on a fresh login) is a one-liner deferred to a Phase 9 cleanup pass.

**Rationale:** Without guest carts, the J-01 journey breaks (customer adds to cart, hits auth wall, loses cart on login). Phase 8.5 cookie + `CartService.merge_guest_into_user` covers the spec; the auth-flow wiring is mechanical.

**Trade-offs:** Cookie-based session adds CSRF surface — mitigated by SameSite=Lax + the cookie being only useful for the specific guest's cart. Authenticated users ignore the cookie entirely.

**Reversibility:** Easy — drop the cookie dependency and require auth at first cart write. Would break J-01.

**References:** `app/api/v1/cart.py:_ensure_session_cookie`; `app/api/deps.py:get_cart_owner`; `app/domain/orders/cart_service.py:merge_guest_into_user`; PRODUCT §7.1, §F-CART-001.

---

### 2026-05-03 — `Payment.is_refund` boolean discriminates charges from refunds
**Phase:** 9
**Context:** PRODUCT §11 talks about "payments" as one stream and "refunds" as another, but the spec doesn't pin down whether they live in one table or two. Phase 9 needs a Payment-stub model so the lifecycle's `refund` transition has somewhere to write a record (Phase 10 will reconcile against Freedom Pay webhooks).
**Decision:** Single `payments` table with `is_refund: bool` (default `false`) and the same `status` lifecycle (`pending|succeeded|failed|refunded`) for both. A successful card charge at place-order time writes one `Payment(is_refund=False, status='succeeded')` (Phase 10 will own the create); an admin refund writes one `Payment(is_refund=True, status='pending')` that the Freedom Pay webhook flips to `succeeded` once the gateway acknowledges.
**Alternatives considered:** (a) Separate `payments` + `refunds` tables — duplicates schema and complicates `total_paid` calculations. (b) Use `amount: Decimal` with a sign convention (positive = charge, negative = refund) — cute but loses the explicit semantic and breaks the `amount > 0` CHECK that protects against zero-value rows.
**Rationale:** One table keeps `SELECT SUM(amount) WHERE order_id=? AND is_refund=false` and the symmetric refund query trivial. The boolean reads cleaner than a sign convention for non-finance engineers picking this up later.
**Trade-offs:** Aggregate queries always need the `is_refund` filter — easy to forget. Mitigated by naming queries `total_charged_for_order` / `total_refunded_for_order` rather than a generic `payments_for_order`.
**Reversibility:** Easy — splitting into two tables is a routine migration; the inverse is trickier.
**References:** `app/domain/orders/models.py:Payment`; `migrations/versions/20260502_2136_create_payments_courier_columns.py`; PRODUCT §11.

---

### 2026-05-03 — Courier info stays inline on `orders` for MVP; deliveries table deferred
**Phase:** 9
**Context:** PHARMACY §7 sketches a future `deliveries` table with courier details, route info, drop-off proof, and status. Phase 9 needs courier name/phone for the `dispatch` transition but nothing else delivery-shaped yet — no proof-of-delivery image, no route, no separate delivery status (the order's own status doubles as the delivery status until launch).
**Decision:** Add `courier_name VARCHAR(120)` + `courier_phone VARCHAR(20)` columns directly on `orders`. Recorded by the `_record_courier` side effect on the `(preparing|ready_for_pickup) → out_for_delivery` transition. No `deliveries` table in Phase 9.
**Alternatives considered:** Stand up the `deliveries` table now with just `courier_name` / `courier_phone` populated. Rejected as YAGNI: the table makes sense once we have route history, drop-off proof, courier accounts, or 1:N deliveries-per-order — none in MVP scope.
**Rationale:** Two columns satisfy every Phase 9 user story. Graduating to a `deliveries` table later is a routine migration (`INSERT INTO deliveries SELECT ... FROM orders WHERE courier_name IS NOT NULL`); doing it now would carry unused tables forever if the feature stays inline.
**Trade-offs:** Schema grows wider; a future `deliveries` table requires backfill. Order detail responses already carry courier info inline, so frontend won't need a refactor either way.
**Reversibility:** Easy — `deliveries` migration plus drop the two columns.
**References:** `app/domain/orders/models.py:Order` (`courier_name`, `courier_phone`); `app/domain/orders/lifecycle.py:_record_courier`; PHARMACY §7 (deliveries deferred).

---

### 2026-05-03 — State transitions encoded as `ALLOWED_TRANSITIONS` config dict (not a dispatch-method-per-pair)
**Phase:** 9
**Context:** The order state machine (PRODUCT §9 + CLAUDE.md "Order state machine" reality check) has ~12 valid transitions, each with its own RBAC, side effects, and `requires_reason` flag. Two encodings: (a) one method per transition that hard-codes its rule and runs its own side effects; (b) a single `ALLOWED_TRANSITIONS: dict[(from, to), TransitionRule]` config that drives a generic `_apply_transition` dispatcher.
**Decision:** (b) — `ALLOWED_TRANSITIONS` dict keyed by `(from_status, to_status)`; each value is a `TransitionRule(allowed_roles, requires_reason, side_effects)`. A single private `_apply_transition` runs validation (state legality → role → reason → branch scope), then applies the status change, runs each side-effect hook, writes the audit row + status_history row, all in one transaction. Public methods (`confirm`, `cancel_by_admin`, etc.) are thin wrappers that supply `(to_status, reason)` and surface clean signatures to routes.
**Alternatives considered:** (a) Per-method state machine — tempting because each transition has bespoke side effects. Rejected because every method ends up duplicating the same 8 lines of role/branch/audit/history boilerplate and drift between them is a real risk (Phase 9 has 8 transitions; Phase 11+ will add more).
**Rationale:** Single source of truth. Adding a new transition is one dict entry plus a hook. RBAC and side-effect lists are auditable in one place. The state-matrix unit test (`test_state_matrix`) reads the dict directly.
**Trade-offs:** The dispatcher is heavier than the simplest per-method form; reading a public method now requires jumping to the dict to understand the rule. Acceptable given the matrix test.
**Reversibility:** Easy — fan out the dispatcher into per-method state if the dict grows unwieldy.
**References:** `app/domain/orders/lifecycle.py:ALLOWED_TRANSITIONS`, `:_apply_transition`; `tests/unit/test_order_lifecycle.py::test_state_matrix`; PRODUCT §9; CLAUDE.md "Order state machine".

---

### 2026-05-03 — Refund flow: COD = status flip only; card = create pending Payment row
**Phase:** 9
**Context:** Admin clicks Refund on a `delivered` order. PRODUCT §11.3 says refunds are admin-initiated; PHARMACY says nothing concrete about how the row is recorded. Two payment methods to handle: COD (no money was ever charged through the gateway — physical cash refund happens out of band) and card (Freedom Pay charge needs an API-level refund call).
**Decision:** The `_create_refund_payment_row` side effect inspects `order.payment_method`. For COD: just flip `order.status = refunded` (and write the audit/status-history rows). No `Payment` insert — there's no charge row to refund and no gateway call to make. For card: write a `Payment(is_refund=True, status='pending')` row with the requested amount + reason. Phase 10's Freedom Pay webhook will flip that row to `succeeded` (or `failed`) when the gateway responds, and at that point we're done. The order status flips to `refunded` immediately either way (admin gets clean UX); the gateway settlement is async.
**Alternatives considered:** (a) Block COD refunds entirely on the API (admin must use a manual-cash workflow). Rejected — admin still wants the order marked as refunded for reporting / audit. (b) Always insert a `Payment(is_refund=True)` row even for COD (with `provider='manual_cash'`). Reasonable; deferred — adds noise to the refunds table without operational payoff at MVP. (c) Wait for the gateway to confirm before flipping status. Rejected — admin UX gets stuck waiting on webhook timing.
**Rationale:** The status-flip-now / settle-later pattern is what gateways assume; it matches Stripe / Freedom Pay's own UI semantics and keeps the admin queue clean. COD doesn't need a Payment row because there's no machine-readable counterparty.
**Trade-offs:** A card refund whose gateway call ultimately fails leaves the order at `refunded` but the `Payment(is_refund=True)` row at `failed` — admin needs to retry or manually reconcile. Phase 10 will wire a notification on stuck refunds.
**Reversibility:** Easy — the rule lives in one method.
**References:** `app/domain/orders/lifecycle.py:_create_refund_payment_row`; PRODUCT §11.3.

---

### 2026-05-03 — Sales report excludes cancelled + refunded orders from revenue (counts them separately)
**Phase:** 9
**Context:** What revenue does the admin sales report show? Three reasonable definitions: (a) gross — sum of all orders with status in `(delivered, ...)` regardless of cancellations, (b) net — sum minus cancelled and refunded, (c) gross-with-callouts — sum of non-cancelled non-refunded plus a separate refunded-amount line.
**Decision:** Revenue = `SUM(o.total)` over orders where `status NOT IN ('cancelled', 'refunded')`. Cancelled and refunded order *counts* surface as separate fields (`cancelled_count`, `refunded_count`) on the same `SalesSummary`. AOV = revenue / order_count over the same non-cancelled-non-refunded set. Top-products SQL applies the same exclusion.
**Alternatives considered:** (a) — overstates ops performance. (c) — useful but pushes the refund-amount calculation onto the report query (needs a join to `payments` filtered by `is_refund=true`); deferred to a later iteration.
**Rationale:** Cancelled order = no money moved (reservation released). Refunded order = money returned. Neither belongs in revenue. Keeping the counts separate gives the admin enough signal to spot a refund spike without inflating the headline.
**Trade-offs:** Net-revenue reporting hides COD refunds (no explicit refund-amount line until we add one). The report doesn't break down per-product refunds either; Phase 11+ refund-analytics will if needed.
**Reversibility:** Easy — change one CASE WHEN clause.
**References:** `app/domain/reports/services.py:_sales_summary`, `:_top_products`; `tests/unit/test_reports_service.py`; PRODUCT §13 (reports).

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

### 2026-05-02 — Test MySQL on port 3307 (tmpfs); dev MySQL on 3306 (volume)
**Phase:** 1
**Context:** Tests should not contend with dev DB and should tear down fast.
**Decision:** `mysql-test` service in docker-compose is profile-gated (`--profile test`), uses `tmpfs` for `/var/lib/mysql`, exposes 3307 on the host. `.env.test` references `mysql+asyncmy://test:test@localhost:3307/pharmacy_test`. Dev MySQL stays on 3306 with persistent volume `mysql_data`.
**Alternatives considered:** Single MySQL with multiple databases. Schema-per-test isolation.
**Rationale:** Hard isolation; tmpfs makes test-DB resets near-instant. Different ports avoid accidental dev-data wipes.
**Trade-offs:** Slightly more local resource usage when running tests against compose.
**Reversibility:** Easy.
**References:** docker-compose.yml; .env.test.

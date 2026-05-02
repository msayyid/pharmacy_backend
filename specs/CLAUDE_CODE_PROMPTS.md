# Claude Code Prompts — Pharmacy Platform Build

> **What this file is.** A staged prompt suite for building the Pharmacy Platform backend with Claude Code. Each phase is self-contained, copy-pasteable, and produces something runnable. Phases assume you start from the prior phase's output.
>
> **Why phased.** Long sessions lose context. By breaking work into focused phases with explicit hand-offs (CHANGELOG, decision log, progress tracker), Claude Code can resume cleanly even after a fresh session. Each phase has clear specs to read, a plan-first gate, and a definition of done.
>
> **Companion specs.** All three blueprints live under `/specs`:
> - `PHARMACY_BLUEPRINT.md` — DB schema and system design
> - `BACKEND_BLUEPRINT.md` — FastAPI + SQLAlchemy + MySQL implementation
> - `PRODUCT_BLUEPRINT.md` — product vision, features, business rules

---

## Table of Contents

### Part 1 — How to Use
1. [How to Use This Document](#1-how-to-use-this-document)
2. [Files You'll Maintain](#2-files-youll-maintain)
3. [Operating Principles (Always-On Rules)](#3-operating-principles-always-on-rules)
4. [Tool Usage Playbook](#4-tool-usage-playbook)

### Part 2 — Bootstrap
5. [Phase 0 — Spec Comprehension & Master Plan](#phase-0--spec-comprehension--master-plan)

### Part 3 — Build Phases
6. [Phase 1 — Project Foundation](#phase-1--project-foundation)
7. [Phase 2 — Database Foundation & Alembic](#phase-2--database-foundation--alembic)
8. [Phase 3 — Core Infrastructure](#phase-3--core-infrastructure)
9. [Phase 4 — Identity & Authentication](#phase-4--identity--authentication)
10. [Phase 5 — Catalog Domain & Admin Catalog API](#phase-5--catalog-domain--admin-catalog-api)
11. [Phase 6 — Inventory Domain & Admin Inventory API](#phase-6--inventory-domain--admin-inventory-api)
12. [Phase 7 — Customer Discovery (Browse & Search)](#phase-7--customer-discovery-browse--search)
13. [Phase 8 — Cart, Checkout & Place-Order (FEFO)](#phase-8--cart-checkout--place-order-fefo)
14. [Phase 9 — Admin Order Lifecycle, Reports & Audit](#phase-9--admin-order-lifecycle-reports--audit)
15. [Phase 10 — Integrations: SMS, Payments, Storage](#phase-10--integrations-sms-payments-storage)
16. [Phase 11 — Background Jobs (ARQ) & Scheduled Tasks](#phase-11--background-jobs-arq--scheduled-tasks)
17. [Phase 12 — Hardening & Launch Readiness](#phase-12--hardening--launch-readiness)

### Part 4 — Meta-Prompts
18. [Code Review Prompt](#code-review-prompt)
19. [Debugging Prompt](#debugging-prompt)
20. [Spec Ambiguity Resolution Prompt](#spec-ambiguity-resolution-prompt)
21. [Context Recovery Prompt (Resume after a Break)](#context-recovery-prompt-resume-after-a-break)
22. [Refactor Prompt](#refactor-prompt)

### Part 5 — Templates & What Else to Add
23. [Templates: BUILD_PROGRESS, DECISION_LOG, ADR, PR, Commits](#templates)
24. [What Else to Add Before You Start Coding](#what-else-to-add-before-you-start-coding)

---

## 1. How to Use This Document

**The intended workflow:**

1. Drop the three blueprint files and this prompts file into a new repository under `/specs`.
2. Open Claude Code in the repo root.
3. Run **Phase 0** — Claude Code reads the specs and produces a master plan. **Approve the plan** before continuing. Do not skip this.
4. Run phases 1 through 12 sequentially, one per session (or one per day, or one per logical batch — your pace).
5. At the end of every phase, Claude Code updates `BUILD_PROGRESS.md`, `DECISION_LOG.md`, and `CHANGELOG.md`. These are the breadcrumb trail that lets the next session resume cleanly.
6. Use the meta-prompts (Part 4) whenever needed — code review at PR time, debugging on failure, recovery if context is lost.

**One prompt = one focused session.** Don't paste two phase prompts back-to-back. Each phase ends with a hand-off. Start the next phase fresh.

**Approve plans before code.** Every phase asks Claude Code to produce a plan first and *wait*. Read the plan. If it's wrong, push back. If it's right, say "Plan approved. Proceed."

**When in doubt, point Claude Code at a section.** If output drifts from the spec, the fix is usually "Re-read PRODUCT_BLUEPRINT §17.2 and adjust." Specific section references work better than vague redirection.

---

## 2. Files You'll Maintain

These files live in the repo root and are updated by Claude Code at every phase boundary. They are the project's persistent memory across sessions.

| File | Purpose | Updated when |
|---|---|---|
| `BUILD_PROGRESS.md` | Current phase, what's done, what's next | End of every phase |
| `DECISION_LOG.md` | Non-obvious choices with rationale | When a real decision is made |
| `CHANGELOG.md` | Human-readable history (Keep a Changelog format) | End of every phase |
| `OPEN_QUESTIONS.md` | Unresolved spec ambiguities | When something is unclear |
| `RISKS.md` | Active risks and mitigations | When new risks surface |
| `docs/adr/NNNN-title.md` | Architecture Decision Records (one per major call) | When the choice deserves persistence |

Templates for each are in §23.

---

## 3. Operating Principles (Always-On Rules)

> Claude Code: these rules apply to **every** phase. Re-read them at the start of every session.

1. **Read specs before you code.** The blueprints are 6,700+ lines for a reason. When a phase prompt cites sections, read those sections in full — don't skim.
2. **Plan before you implement.** Every phase requires a written plan, approved before coding. Plans surface bad ideas cheaply.
3. **Stay in scope.** Each phase has explicit "out of scope" items. If a thought starts with "while I'm here, I might as well…" — stop. Note it in `BUILD_PROGRESS.md > Backlog` and move on.
4. **Be a senior engineer, not a cargo cult.** If a spec instruction looks wrong, *say so* before implementing. Don't silently work around it.
5. **Test as you build, not after.** Every model gets a repository test, every endpoint gets at least a happy-path E2E test. Tests are part of the phase, not "Phase 13."
6. **Surface ambiguity, don't paper over it.** If two specs disagree or a case isn't covered, add to `OPEN_QUESTIONS.md` and ask. Don't invent.
7. **No silent assumptions.** If you generated something the spec didn't dictate (a default value, an edge case behaviour), log it in `DECISION_LOG.md`.
8. **Conventional Commits.** Every commit follows `type(scope): subject` (see §23.5). Squash-merge per phase or per logical chunk.
9. **Run before declaring done.** Code that hasn't been executed isn't done. Run the migration, hit the endpoint, watch the test pass.
10. **Backend §27 + Product §26 are gates.** Before declaring any phase complete, walk both checklists and confirm.

---

## 4. Tool Usage Playbook

> When and how to use Claude Code's capabilities effectively for this project.

### 4.1 Deep thinking (extended reasoning)

**Use it when:**
- Designing a transaction with concurrency concerns (place-order FEFO is the canonical example)
- Choosing between two architectural options
- Tracing a subtle bug
- Deciding whether to deviate from a spec

**How to invoke:** Include explicit reasoning instructions in prompts ("think step by step about race conditions," "ultrathink about how this scales"). Don't use deep thinking for routine CRUD generation — it's wasted time.

### 4.2 Sub-agents (parallel work via Task tool)

**Use them when:**
- A phase has independent research streams (e.g., "research MySQL ngram parser tuning" + "scaffold the search service")
- You need to read and summarise a large body of code that would blow your main context
- Two parts of the work don't share files

**Don't use them when:**
- The work is sequential (sub-agent A's output feeds sub-agent B — just do it sequentially)
- The whole phase fits in one focused pass
- The work modifies the same files (merge conflicts hurt)

**Pattern that works well:**
> "Spawn two sub-agents in parallel:
> Agent A: Read every SQLAlchemy model in `app/domain/` and summarise the relationships.
> Agent B: Read `BACKEND_BLUEPRINT.md` §6 and §8 and produce a checklist of MySQL adaptations needed for the new model.
> When both finish, synthesise."

### 4.3 Web research

**Use it when:**
- A library version may have changed since training (FastAPI, SQLAlchemy, Alembic, asyncmy, ARQ, Pydantic)
- You're implementing something where a current best practice may exist (rate limiting patterns, OAuth flows, MySQL ngram tuning)
- A library error message suggests a known issue with a documented workaround

**Don't use it for:**
- General Python knowledge
- Pharmacy domain (the specs cover it)
- Project conventions (the specs cover them)

### 4.4 Plan mode / TodoWrite

**Use TodoWrite at the start of every phase** to break the phase into 6–15 trackable items. Mark items in-progress and complete as you go. This keeps the phase focused and gives you a recovery point if the session is interrupted.

### 4.5 Reading vs running

For exploration of *this* codebase: prefer reading files directly.
For *external* libraries: read the source if installed; otherwise fetch docs.
For verifying behaviour: actually run code (pytest, alembic, curl). Don't reason about runtime behaviour from source alone when you can run it.

---

## Phase 0 — Spec Comprehension & Master Plan

**Goal of this phase.** Claude Code reads all three blueprints end-to-end, builds an internal model of the system, and produces a master plan that proves it understood. No code is written. This phase's output is documents.

**Input.** Three blueprints in `/specs`. An empty repository (other than `/specs`).
**Output.** `BUILD_PLAN.md`, `BUILD_PROGRESS.md`, `OPEN_QUESTIONS.md`, `RISKS.md`, an empty `DECISION_LOG.md`, an empty `CHANGELOG.md`, and a chat-channel summary of the plan.
**Estimated session length.** 60–90 minutes.

### The prompt

```
You are a senior staff engineer joining the Pharmacy Platform project. Today is
day one. Three specification documents already exist in /specs:

  /specs/PRODUCT_BLUEPRINT.md      (1,759 lines — product vision, features, rules)
  /specs/BACKEND_BLUEPRINT.md      (2,879 lines — FastAPI + SQLAlchemy + MySQL)
  /specs/PHARMACY_BLUEPRINT.md     (2,133 lines — DB schema and system design)
  /specs/CLAUDE_CODE_PROMPTS.md    (this file — phased build prompts)

Your mission for this session: read all three blueprints end-to-end, build a
deep mental model, and produce a master plan. NO CODE in this phase.

────────────────────────────────────────────────────────────────────────────
HOW TO APPROACH

1. Use deep thinking. This is the most important reading session of the
   project. Skimming now causes weeks of rework later. Take your time.

2. Read in this order:
     a. PRODUCT_BLUEPRINT.md  (the WHY and WHAT)
     b. PHARMACY_BLUEPRINT.md (the DATA shape and SYSTEM architecture)
     c. BACKEND_BLUEPRINT.md  (the HOW for the backend)
   Reading product first prevents the trap of designing data without
   understanding the user.

3. Optionally launch a parallel sub-agent (Task tool) to extract the
   feature ID catalog (every F-* identifier) from the product blueprint
   while you read the database blueprint. Synthesise both.

4. As you read, take notes. Build:
     - A map of every domain (identity, catalog, inventory, orders, etc.)
       and the tables, services, and endpoints in each
     - A list of cross-cutting concerns (auth, i18n, caching, audit, jobs)
     - A list of every place where the three specs disagree, are silent,
       or need a judgement call
     - A list of risks specific to this build

5. Produce the deliverables below. Plan before writing them — sketch
   the structure, then fill in.

────────────────────────────────────────────────────────────────────────────
DELIVERABLES (files to create in repo root)

A. BUILD_PLAN.md
   The master plan. Sections:
     1. System summary in your own words (≤ 400 words). Prove you
        understood — explain the place-order FEFO transaction, the
        multi-language model, the role-based admin model, and how
        inventory truth is maintained.
     2. Phase-by-phase build order (mirror Phases 1–12 in the prompts
        file but in YOUR words, with YOUR estimates of effort and risk).
     3. Critical path: which phases block which.
     4. Architecture validation: walk through every spec recommendation
        and either endorse it or push back with an alternative.
     5. Tech stack inventory with pinned versions (from BACKEND §2),
        and a note on each: is the version current? Any compatibility
        risks? (Use web search if uncertain.)

B. BUILD_PROGRESS.md
   Use the template in §23.1 of CLAUDE_CODE_PROMPTS. Mark Phase 0 as
   in-progress. Initialize all phases.

C. OPEN_QUESTIONS.md
   Every ambiguity, conflict, or judgement call you found while
   reading. Format: question, where it surfaced (file/section),
   proposed default if unanswered, who should decide.
   Examples to look for:
     - Cold-chain summer surcharge amount is "Phase 2" — does the
       schema need any column for it now?
     - Customer email is optional — what triggers receipt email?
     - Backend says ARQ; product says nothing about job tooling
       choice — anything to flag?
     - The 30-day shelf-life-at-dispatch rule (PRODUCT §5.5) vs the
       7-day hard block (PHARMACY §5.5 / BACKEND nothing) —
       enforcement layer?

D. RISKS.md
   Top 10 risks ranked, each with: likelihood, impact, mitigation owner,
   trigger condition. Pull from PHARMACY §24 and PRODUCT §24 but add
   build-specific risks (e.g. "MySQL ngram parser may not handle
   Kyrgyz well — need real-data test in Phase 7").

E. DECISION_LOG.md
   Initialize empty per template §23.2.

F. CHANGELOG.md
   Initialize per Keep a Changelog format, §23.3. Add an "Unreleased"
   section with one entry: "Project initialised; specs and master plan
   in place."

────────────────────────────────────────────────────────────────────────────
QUALITY BAR

- BUILD_PLAN.md must demonstrate you read the specs, not summarise them.
  Specifically: in §1, explain in your own words why FEFO + reservation
  + snapshot is the design (not just describe that it exists).
- OPEN_QUESTIONS.md must contain at least 8 substantive items. If you
  found fewer, you didn't read carefully enough.
- Use precise references: "PRODUCT §5.5", "BACKEND §11.2", not "the
  spec says somewhere".

────────────────────────────────────────────────────────────────────────────
WHEN COMPLETE

1. Update BUILD_PROGRESS.md: Phase 0 → done.
2. Post in chat:
     - 5-bullet executive summary of the plan
     - The top 3 open questions blocking Phase 1
     - Confirmation that you're ready for Phase 1 once questions are
       resolved
3. STOP. Wait for plan review. Do not start Phase 1 until the human
   says "Plan approved. Proceed to Phase 1."
```

### Definition of Done

- [ ] Six files created in repo root: `BUILD_PLAN.md`, `BUILD_PROGRESS.md`, `OPEN_QUESTIONS.md`, `RISKS.md`, `DECISION_LOG.md`, `CHANGELOG.md`
- [ ] BUILD_PLAN.md proves comprehension (the FEFO and i18n sections in your own words)
- [ ] OPEN_QUESTIONS.md has ≥ 8 substantive items
- [ ] Top 3 questions surfaced in chat
- [ ] Claude Code stopped and is waiting for approval

### Hand-off

After approving the plan, paste the Phase 1 prompt in a fresh session.

---

## Phase 1 — Project Foundation

**Goal.** A runnable FastAPI app with the agreed directory structure, dependency management, configuration, logging, error handling, middleware, Docker compose for local dev, and CI scaffolding. Everything *infrastructural*; no domain code yet.

**Input.** Approved master plan from Phase 0.
**Output.** A repo where `make dev` runs and `GET /health` returns 200 with structured logs.
**Estimated session length.** 90–120 minutes.

### The prompt

```
You are a senior backend engineer building the project foundation for the
Pharmacy Platform. Phase 0 is complete; the master plan is approved.

────────────────────────────────────────────────────────────────────────────
SPECS TO RE-READ BEFORE PLANNING

Required:
  - BACKEND_BLUEPRINT §2  (Tech Stack & Pinned Versions)
  - BACKEND_BLUEPRINT §3  (Directory Structure)
  - BACKEND_BLUEPRINT §4  (Naming Conventions)
  - BACKEND_BLUEPRINT §5  (Configuration & Environments)
  - BACKEND_BLUEPRINT §15 (Validation, Errors & Exception Handling)
  - BACKEND_BLUEPRINT §16 (Middleware & Cross-cutting Concerns)
  - BACKEND_BLUEPRINT §19 (Logging)
  - BACKEND_BLUEPRINT §24 (Code Quality)
  - BACKEND_BLUEPRINT §25 (Local Development)

Skim:
  - PRODUCT_BLUEPRINT §1  (Rules for Claude Code)
  - PHARMACY_BLUEPRINT §22 (Deployment Topology — for context)

────────────────────────────────────────────────────────────────────────────
MISSION

Stand up the project skeleton so the next phases drop into a working frame.
After this phase:
  - `make install` installs dependencies
  - `docker compose up -d mysql redis` brings up local infra
  - `make dev` starts the API on localhost:8000
  - `GET /health` returns {"status":"ok"} with a structured JSON log line
  - `make lint`, `make type`, `make test` all pass on an empty test suite
  - Pre-commit hooks installed and passing
  - Sentry SDK initialised but not capturing (DSN optional)
  - GitHub Actions workflow runs lint+type+test on PR

NO domain code. NO routers beyond /health. NO models. NO migrations
(those come in Phase 2).

────────────────────────────────────────────────────────────────────────────
PLAN FIRST (do not skip)

1. Use deep thinking to design the foundation. Consider:
     - Is uv the right package manager vs poetry? (Backend §2 implies uv;
       confirm and decide.)
     - Where do you initialise structlog so workers and tests share config?
     - Lifespan vs startup events for FastAPI?
     - Production vs development docker images — one Dockerfile multistage
       or two?

2. Optionally launch a sub-agent to verify current versions of the libs
   in BACKEND §2 are still latest stable (web search). Report deviations.

3. Use TodoWrite to break this into 8–12 trackable items.

4. Write your plan as a chat response with:
     - File-by-file what you'll create
     - Order of creation
     - Test plan (what minimal tests prove it works)
     - Risks & mitigations
     - Open questions (add to OPEN_QUESTIONS.md if any)

5. STOP. Wait for "Plan approved. Proceed."

────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION GUIDANCE

- Follow BACKEND §3 directory layout exactly. Even empty directories
  matter — create them with .gitkeep so the layout is real on day one.

- pyproject.toml with the exact deps in BACKEND §2. Use uv for env
  management unless you have a compelling reason to deviate (and if so,
  log it in DECISION_LOG.md and surface it).

- app/main.py creates the FastAPI app via a create_app() factory and
  uses ORJSONResponse as default response class. Wire only:
     - /health endpoint (returns {"status":"ok","version":...})
     - RequestIdMiddleware
     - AccessLogMiddleware
     - Exception handlers for AppError, RequestValidationError,
       Exception (per BACKEND §15.2)
     - CORS middleware (read settings.cors_origins)

- app/core/config.py is the full Settings class from BACKEND §5.1.
  Provide a complete .env.example with comments per variable.

- app/core/errors.py is the full hierarchy from BACKEND §15.1.

- app/core/logging.py per BACKEND §19.1 — structlog with request_id
  context, JSON output, PII-redaction processor for any field named
  password, code, token, or otp.

- Pre-commit config from BACKEND §24.4. Run `pre-commit install` as
  the last setup step.

- Dockerfile multistage: builder + runtime. Production CMD per
  BACKEND §25 (gunicorn with uvicorn workers).

- docker-compose.yml per BACKEND §25 with mysql 8.4 and redis 7.

- Makefile per BACKEND §25.1, plus targets for: docker-up, docker-down,
  shell (open psql/redis-cli? — no: mysql shell and redis-cli), and
  pre-commit.

- GitHub Actions workflow at .github/workflows/ci.yml:
     - on pull_request and push to main
     - sets up Python 3.12, uv
     - runs ruff, mypy, pytest (against ephemeral mysql+redis services)
     - caches uv

- README.md: how to run locally in 5 minutes flat. Include
  prerequisites (Python 3.12, Docker), commands, and where to look in
  /specs for context.

────────────────────────────────────────────────────────────────────────────
TEST EXPECTATIONS FOR THIS PHASE

Minimum tests to write (real assertions, not placeholders):
  - tests/conftest.py with the fixtures from BACKEND §23.2
  - tests/integration/test_health.py: GET /health returns 200 with
    expected shape
  - tests/integration/test_request_id.py: request_id round-trips via
    header
  - tests/unit/test_config.py: settings load from .env.test
  - tests/unit/test_errors.py: AppError → ProblemDetail JSON
  - tests/unit/test_logging.py: PII redaction works for password/code

────────────────────────────────────────────────────────────────────────────
OUT OF SCOPE — DO NOT BUILD IN THIS PHASE

  - Any database models or migrations (Phase 2)
  - Any domain folders beyond empty .gitkeep'd directories
  - Redis client setup beyond settings (Phase 3)
  - Auth code (Phase 4)
  - Any routes beyond /health
  - ARQ worker (Phase 11)

If you find yourself reaching into one of these — stop, log a backlog
note, finish the foundation work.

────────────────────────────────────────────────────────────────────────────
DEFINITION OF DONE

  [ ] Repo structure matches BACKEND §3 (with empty dirs holding
      .gitkeep where applicable)
  [ ] `make install` succeeds on a clean machine
  [ ] `docker compose up -d mysql redis` brings up healthy services
  [ ] `make dev` starts the app and /health returns 200
  [ ] `make lint` passes (ruff check + ruff format check)
  [ ] `make type` passes (mypy --strict on app/)
  [ ] `make test` passes (the seven minimal tests above)
  [ ] pre-commit hooks installed and a sample commit triggers them
  [ ] GitHub Actions workflow committed and dry-runnable
  [ ] README.md gets a new dev to "/health returns 200" in under 5 min
  [ ] BACKEND §27 conventions checklist satisfied for the foundational
      code (structure, naming, async correctness on /health, type hints)

────────────────────────────────────────────────────────────────────────────
HAND-OFF

  1. Update BUILD_PROGRESS.md: Phase 1 → done. Phase 2 → next.
  2. Update CHANGELOG.md under Unreleased with what shipped this phase.
  3. Update DECISION_LOG.md with any non-obvious choices (e.g. uv vs
     poetry, multistage vs single Dockerfile).
  4. If any open questions were resolved, mark them resolved in
     OPEN_QUESTIONS.md.
  5. Post in chat:
       - One-paragraph summary of what shipped
       - Anything notable / surprising
       - Confirmation the next prompt (Phase 2) is safe to run
  6. STOP. Do not begin Phase 2.
```

### Definition of Done

See the prompt's DoD block. Don't start Phase 2 until every box is ticked.

### Hand-off

`BUILD_PROGRESS.md` and `CHANGELOG.md` updated; the foundation is committable. The next session should be able to `git pull && make dev` and immediately resume.

---

## Phase 2 — Database Foundation & Alembic

**Goal.** All the infrastructure to define and migrate models — but no models yet (beyond what proves the wiring works). Async engine, session management, the `GUID` type, mixins, Alembic configured for async, MySQL settings verified, an initial empty migration applied.

**Input.** Phase 1 done.
**Output.** `alembic upgrade head` runs cleanly against the local MySQL container; a smoke test connects, queries, and writes.
**Estimated session length.** 60–90 minutes.

### The prompt

```
You are a senior backend engineer wiring up the database layer for the
Pharmacy Platform. Phase 1 is complete; the project foundation runs.

────────────────────────────────────────────────────────────────────────────
SPECS TO RE-READ

Required:
  - BACKEND_BLUEPRINT §6  (MySQL Adaptation Guide — every word matters)
  - BACKEND_BLUEPRINT §7  (Database Layer — engine, session, custom types)
  - BACKEND_BLUEPRINT §8  (SQLAlchemy Models — base, mixins, conventions)
  - BACKEND_BLUEPRINT §9  (Alembic Migrations — async setup, FULLTEXT recipe)
  - BACKEND_BLUEPRINT §22.1, §22.2 (server settings)
  - PHARMACY_BLUEPRINT §6.4 (FULLTEXT search — for context, not implementation
    yet)

Skim:
  - PHARMACY_BLUEPRINT §2 (extensions — note these are PG-specific; ignore)

────────────────────────────────────────────────────────────────────────────
MISSION

After this phase:
  - SQLAlchemy async engine and session factory work
  - The GUID custom type encodes/decodes UUIDv7 cleanly to/from BINARY(16)
  - Base, TimestampMixin, SoftDeleteMixin are defined and importable
  - Alembic is configured for async and points at app metadata
  - MySQL container has the project's database with the correct charset
    and collation
  - An initial migration creates a tiny "ping" table to prove the path
    works end-to-end (we'll drop it in Phase 4 when real models land)
  - A smoke test connects, inserts, reads back

NO real domain models in this phase.

────────────────────────────────────────────────────────────────────────────
PLAN FIRST

1. Use deep thinking on these questions:
     - How does GUID's byte-swap (BACKEND §7.2) play with Alembic's
       autogenerate? Will it produce stable diffs?
     - Where does Base.metadata get populated when models live in
       multiple files under app/domain/<context>/models.py?
       (BACKEND §9.1 has the env.py imports — confirm pattern.)
     - The session expire_on_commit=False decision — what's the
       trap for FastAPI handlers that read attributes after commit?
     - What goes in the initial migration vs leaves space for
       real models in Phase 4?

2. Optionally launch a parallel sub-agent:
     Agent A: Read BACKEND §6 in full and extract every MySQL-specific
              pattern that affects model definition (charset, collation,
              CHECK constraints, partial-unique workarounds, FULLTEXT
              prefix). Produce a checklist.
     Agent B: Read BACKEND §8 and verify the example Product model is
              internally consistent and uses MySQL-safe patterns.
              Produce a "reference card" of the conventions.

3. Use TodoWrite to plan 8–12 items. Include:
     - Configure my.cnf / docker compose to ensure server-level
       charset and sql_mode (BACKEND §6.1)
     - app/core/db.py engine + session
     - app/core/types.py GUID
     - app/core/db_base.py Base + mixins
     - alembic init + env.py + script.py.mako
     - Initial migration: ping table
     - Smoke test
     - Makefile targets (migrate, revision)

4. Write the plan in chat. Include:
     - File-by-file changes
     - Migration strategy for the placeholder table
     - How you'll verify each piece (commands you'll run)
     - Risks (esp. around BINARY(16) GUID stability)

5. STOP. Wait for "Plan approved."

────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION GUIDANCE

- docker-compose mysql command must include the full set from BACKEND §6.1.
  Verify by running `SHOW VARIABLES LIKE 'character_set%';` and
  `SHOW VARIABLES LIKE 'sql_mode';` after up. Add an integration test
  that asserts character_set_database = utf8mb4 and the expected
  collation.

- app/core/db.py:
     - create_async_engine with pool_size, max_overflow, pool_recycle,
       pool_pre_ping (per BACKEND §7.5)
     - SessionLocal as async_sessionmaker with expire_on_commit=False
     - get_db() FastAPI dependency that commits on success, rolls back
       on exception (BACKEND §7.1 has the exact code)
     - session_scope() context manager for workers/scripts

- app/core/types.py: GUID per BACKEND §7.2 verbatim. The byte-swap
  matters — without it, B-tree index locality is bad.

- For UUIDv7 generation, use the `uuid_extensions` library or `uuid7`
  package. If neither is in BACKEND §2 deps, add the smallest one and
  log in DECISION_LOG.

- app/core/db_base.py: Base + TimestampMixin + SoftDeleteMixin
  (BACKEND §7.3). Important: utc_timestamp(6) for fractional seconds.

- alembic init alembic. Then customize:
     - alembic.ini per BACKEND §9.1
     - migrations/env.py per BACKEND §9.1 (async-friendly version)
     - script.py.mako keeps the default

- For env.py, since no domain models exist yet, leave the model-
  imports comment block in place but don't import yet. Phase 4 fills
  this in. Add a TODO comment with a pointer.

- Initial migration:
     - Created with `alembic revision --autogenerate -m "init ping"`
     - Adds a single `ping` table with id INT PK and message VARCHAR(50)
     - This table will be dropped in Phase 4 when real models arrive
       (note this in CHANGELOG and DECISION_LOG)
     - Includes mysql_engine='InnoDB', mysql_charset='utf8mb4',
       mysql_collate='utf8mb4_0900_ai_ci' on the table args

- Makefile targets: migrate (alembic upgrade head),
  revision (alembic revision --autogenerate -m "$(m)"),
  downgrade (alembic downgrade -1)

────────────────────────────────────────────────────────────────────────────
TEST EXPECTATIONS FOR THIS PHASE

  - tests/integration/test_db_charset.py: asserts MySQL is configured
    with utf8mb4 + utf8mb4_0900_ai_ci + correct sql_mode
  - tests/integration/test_db_session.py: opens a session, inserts a
    ping row, reads it back, asserts UTC timestamps
  - tests/unit/test_guid_type.py: round-trips a known UUID through
    GUID.process_bind_param + process_result_value, asserts equality
    and asserts byte order matches MySQL UUID_TO_BIN(_, 1)
  - tests/integration/test_alembic_smoke.py: runs alembic upgrade head
    against an ephemeral MySQL, then alembic downgrade base, asserts
    no errors

────────────────────────────────────────────────────────────────────────────
OUT OF SCOPE — DO NOT BUILD

  - Any real domain models (Phase 4 onward)
  - Redis client (Phase 3)
  - Security primitives (Phase 3)
  - Auth (Phase 4)
  - Anything in the FULLTEXT search path (Phase 7)

────────────────────────────────────────────────────────────────────────────
DEFINITION OF DONE

  [ ] docker compose mysql brings up with correct charset/collation/
      sql_mode (verified by test)
  [ ] app/core/db.py provides async engine, SessionLocal, get_db,
      session_scope
  [ ] app/core/types.py provides GUID and round-trip is asserted
  [ ] app/core/db_base.py exports Base, TimestampMixin, SoftDeleteMixin
  [ ] alembic initialized; env.py is async-friendly
  [ ] Initial migration creates ping table; upgrade and downgrade work
  [ ] Smoke test inserts and reads from ping table
  [ ] make migrate / make revision targets work
  [ ] All tests in this phase pass; mypy and ruff still clean
  [ ] BACKEND §27 conventions check passes for the new code

────────────────────────────────────────────────────────────────────────────
HAND-OFF

  1. Update BUILD_PROGRESS.md: Phase 2 → done.
  2. CHANGELOG.md updated.
  3. DECISION_LOG.md notes:
       - Why the byte-swap GUID
       - Why a placeholder ping table (and that Phase 4 will drop it)
       - Any deviation from BACKEND §6 with rationale
  4. Post in chat:
       - What shipped
       - Anything that surprised you about MySQL or asyncmy
       - Status of OPEN_QUESTIONS.md items affected by this phase
  5. STOP.
```

### Definition of Done & Hand-off

See prompt. Verify alembic round-trip works before declaring done.

---

## Phase 3 — Core Infrastructure

**Goal.** All cross-cutting infrastructure that domains will lean on: Redis client, security primitives (argon2, JWT, OTP hashing, phone normalization), rate limiting, caching helpers, pagination, i18n, time helpers. No domain code.

**Input.** Phase 2 done.
**Output.** `app/core/*` is fully populated and unit-tested. Identity in Phase 4 can build directly on top.
**Estimated session length.** 90–120 minutes.

### The prompt

```
You are a senior backend engineer building the cross-cutting infrastructure
for the Pharmacy Platform. Phases 1–2 are complete.

────────────────────────────────────────────────────────────────────────────
SPECS TO RE-READ

Required:
  - BACKEND_BLUEPRINT §14.6 (Password & OTP hashing)
  - BACKEND_BLUEPRINT §17    (Caching — Redis client, key conventions)
  - BACKEND_BLUEPRINT §18    (Caching helpers and rate limiter)
  - BACKEND_BLUEPRINT §20    (Pagination)
  - BACKEND_BLUEPRINT §21    (Idempotency)
  - BACKEND_BLUEPRINT §22    (i18n)
  - PRODUCT_BLUEPRINT §16    (Localization)
  - PRODUCT_BLUEPRINT §21    (User-Facing Copy — informs i18n shape)

Skim:
  - PHARMACY_BLUEPRINT §17.4, §17.5 (cache + rate limit context)

────────────────────────────────────────────────────────────────────────────
MISSION

After this phase, the following are done and tested:
  - Redis client with init_redis / close_redis / get_redis (lifespan-
    aware)
  - app/core/security.py: hash_password, verify_password, hash_otp,
    verify_otp, generate_numeric_code, normalise_phone (E.164 via
    phonenumbers), TokenIssuer for JWT
  - app/core/ratelimit.py: hit() with sliding window (Redis pipeline)
  - app/core/cache.py: cache_get_or_set, invalidate(prefix)
  - app/core/pagination.py: PageParams, page_params dependency,
    Page[T], Cursor[T] envelopes, parse_sort allow-list helper
  - app/core/i18n.py: resolve_language; load translation dicts from
    JSON files under app/i18n/<lang>.json (RU is mandatory; KY/EN
    optional, fall back to RU)
  - app/core/time.py: utcnow(), bishkek_now(), to_bishkek
  - app/core/idempotency.py: idempotency-key store helper for Phase 8

NO domain code. NO routers. Wiring into FastAPI lifespan happens here
(init_redis on startup, close on shutdown).

────────────────────────────────────────────────────────────────────────────
PLAN FIRST

1. Deep thinking on:
     - Redis client lifecycle in tests — how do tests get a Redis
       client without depending on the global? (Hint: dependency
       overrides + a fixture.)
     - Rate limit semantics: fixed window vs sliding window. Backend
       §18.5 hints at an INCR+EXPIRE pattern; that's a token bucket
       approximation. Confirm it matches PRODUCT §16 expectations.
     - JWT key handling: HS256 with secret is fine for now. Is key
       rotation in scope (BACKEND §20.3 mentions 90-day rotation)?
       Decision: scaffold key id (kid) header but don't implement
       rotation. Log in DECISION_LOG.
     - i18n: where do JSON translation files live, and how do they
       relate to PRODUCT §21? Suggestion: app/i18n/ru.json,
       ky.json, en.json. Initial content is the table from
       PRODUCT §21.2 plus SMS templates §21.3. Keep keys snake_case.

2. Sub-agents (optional):
     Agent A: Survey libraries — phonenumbers, python-jose, passlib
              (argon2), redis-py async — for any version-specific
              gotchas. Web search latest issues.
     Agent B: Read PRODUCT §21 in full and produce the initial
              ru.json with all the keys. Also stub ky.json and
              en.json with same keys, RU values, and a TODO marker.

3. TodoWrite plan with 10–14 items.

4. Plan in chat. Wait for approval.

────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION GUIDANCE

- app/core/redis.py per BACKEND §18.1.

- app/core/security.py:
     - argon2id via passlib (cost from BACKEND §14.6)
     - JWT issuer with access (15 min) + refresh (30 days), kid header,
       jti claim from uuid7
     - hash_otp/verify_otp via HMAC-SHA256 with pepper
     - generate_numeric_code(n) using secrets module
     - normalise_phone using phonenumbers, default region "KG"
       (PRODUCT §16.5)

- app/core/ratelimit.py per BACKEND §18.5. Add a docstring with worked
  example: "3 requests per 15 minutes per phone".

- app/core/cache.py per BACKEND §18.3. Use orjson for serialization.
  Include invalidate_keys for batch deletion via pipeline.

- app/core/pagination.py per BACKEND §10.4 (envelopes) and §20
  (helpers). Cursor encoding: base64-encoded JSON of (created_at, id)
  for keyset pagination.

- app/core/i18n.py:
     - Load translation files lazily on first use; cache in module
     - Provide t(key: str, lang: str, **vars) -> str
     - Variable interpolation via str.format
     - On missing key in target lang, fall back to default_language
       (settings)
     - On missing key in default_language, log a warning and return
       the key (so it surfaces in tests/logs)

- app/i18n/ru.json: initial keys per PRODUCT §21.2 and §21.3.
  Use exactly the strings provided. ky.json same keys, KY values
  where given else RU placeholder with TODO. en.json same with EN
  values where given.

- app/core/time.py: utcnow() returns timezone-aware UTC datetime.
  bishkek_now returns timezone-aware Asia/Bishkek datetime. Use
  zoneinfo.

- app/core/idempotency.py: store(key, response_dict, ttl), check(key,
  body_digest) -> "hit_same" | "hit_different" | "miss". TTL default
  24h.

- main.py lifespan extended to init_redis on startup, close on
  shutdown.

────────────────────────────────────────────────────────────────────────────
TEST EXPECTATIONS

  - tests/unit/test_security_password.py: hash + verify; tampering
    detection; pepper required.
  - tests/unit/test_security_otp.py: generate, hash, verify happy and
    sad paths; constant-time check.
  - tests/unit/test_security_jwt.py: issue access+refresh, decode,
    expired token rejected, wrong-type rejected.
  - tests/unit/test_security_phone.py: parses +996 numbers; rejects
    invalid; defaults region "KG".
  - tests/integration/test_redis_lifecycle.py: lifespan starts client;
    set/get round-trips; close releases.
  - tests/integration/test_ratelimit.py: hits within window allowed;
    over-limit raises; window reset works.
  - tests/integration/test_cache.py: cache_get_or_set with cold miss
    then warm hit; invalidate(prefix) removes matching keys.
  - tests/unit/test_pagination.py: PageParams validation; sort
    parsing rejects unallowed fields; cursor encode/decode round-
    trips.
  - tests/unit/test_i18n.py: resolves language from Accept-Language;
    falls back; interpolates vars; missing-key behaviour logs a
    warning.
  - tests/unit/test_idempotency.py: miss → store → hit_same → hit_
    different.

────────────────────────────────────────────────────────────────────────────
OUT OF SCOPE

  - Domain models (Phase 4+)
  - Auth dependencies that touch DB users (Phase 4)
  - SMS sending (Phase 10)
  - Real ARQ jobs (Phase 11)

────────────────────────────────────────────────────────────────────────────
DEFINITION OF DONE

  [ ] All app/core/* modules exist and pass tests
  [ ] Redis client integrates with FastAPI lifespan
  [ ] i18n JSON files for ru/ky/en exist with the §21 keys
  [ ] All tests above pass; ruff and mypy clean
  [ ] Integration tests run against the docker-compose Redis
  [ ] BACKEND §27 conventions checklist passes for new code

────────────────────────────────────────────────────────────────────────────
HAND-OFF

  1. Update BUILD_PROGRESS, CHANGELOG, DECISION_LOG.
  2. Note in DECISION_LOG: JWT kid scaffolded but rotation deferred;
     ngram_token_size choice for later; i18n missing-key behaviour.
  3. Post chat summary including: what's now ready for Phase 4 to
     consume.
  4. STOP.
```

---

## Phase 4 — Identity & Authentication

**Goal.** End-to-end identity domain: customers, addresses, OTP codes, admin users, admin sessions; the OTP flow that issues JWTs; admin password login with optional TOTP; `get_current_user` and `require_role` dependencies. The `ping` table from Phase 2 is dropped here.

**Input.** Phase 3 done.
**Output.** A real customer can request OTP → verify → receive tokens → call an authenticated endpoint. An admin can log in and receive a session. RBAC dependency works.
**Estimated session length.** 2–3 hours (or split across two sessions on the natural seam: models+services first, API endpoints second).

### The prompt

```
You are a senior backend engineer building the identity domain for the
Pharmacy Platform. Phases 1–3 are complete.

This is the first phase that ships real domain code AND a working API
flow end-to-end. Take it carefully. Do NOT cut corners on tests.

────────────────────────────────────────────────────────────────────────────
SPECS TO RE-READ

Required (in order):
  - PRODUCT_BLUEPRINT §4    (Personas)
  - PRODUCT_BLUEPRINT §7.1  (Journey J-01 — first-time symptom shopper)
  - PRODUCT_BLUEPRINT §8.1  (Auth & account features F-AUTH-001..002,
                             F-ACC-001..004)
  - PRODUCT_BLUEPRINT §17.3 (Auth edge cases)
  - PRODUCT_BLUEPRINT §21   (Copy library — auth keys)
  - BACKEND_BLUEPRINT §11   (Repository layer pattern)
  - BACKEND_BLUEPRINT §12   (Service layer pattern)
  - BACKEND_BLUEPRINT §13   (Routers & dependencies)
  - BACKEND_BLUEPRINT §14   (Authentication & Authorization, all)
  - BACKEND_BLUEPRINT §26   (Vertical slice — OTP request — your blueprint)
  - PHARMACY_BLUEPRINT §4   (Identity & Access schema — full)

────────────────────────────────────────────────────────────────────────────
MISSION

Ship the full identity vertical:

  Models (with migration):
    - users, user_addresses, otp_codes, admin_users, admin_sessions
    - The "one default address per user" partial-unique behaviour via
      generated column (BACKEND §6.5)

  Repositories:
    - UserRepository, UserAddressRepository, OtpRepository,
      AdminUserRepository, AdminSessionRepository

  Services:
    - OtpService (request_code, verify_and_issue_tokens)
    - AuthService (refresh_tokens, logout)
    - AccountService (get_me, update_me, addresses CRUD)
    - AdminAuthService (login_with_password, optional TOTP, logout)

  Schemas:
    - All Create/Update/Read per BACKEND §10
    - OtpRequestIn / OtpRequestOut / OtpVerifyIn / TokenPair /
      RefreshIn / UserMeRead / AddressCreate / AddressRead /
      AddressUpdate / AdminLoginIn / AdminMeRead

  Dependencies (in app/domain/identity/dependencies.py):
    - get_current_user (JWT bearer; rejects wrong type/kind/inactive)
    - get_current_admin (cookie-based admin session)
    - require_role(*roles) factory
    - require_branch_access(param_name) factory

  Customer API (app/api/v1/auth.py + account.py):
    - POST /auth/otp/request
    - POST /auth/otp/verify
    - POST /auth/refresh
    - POST /auth/logout
    - GET  /me
    - PATCH /me
    - GET/POST/PATCH/DELETE /me/addresses[/:id]

  Admin API (app/api/admin_v1/auth.py):
    - POST /admin/auth/login
    - POST /admin/auth/logout
    - GET  /admin/auth/me

The ping table from Phase 2 is dropped in this phase's migration.

────────────────────────────────────────────────────────────────────────────
PLAN FIRST — APPLY DEEP THINKING

This phase has serious surface area. Before writing code, think
carefully about:

1. The OTP request rate-limit composition: per-phone (1/60s, 3/15m)
   AND per-IP (10/h). Both must be enforced. Which Redis key shapes?
   What happens when only one is exceeded?

2. Token rotation on refresh: the spec says "old refresh becomes
   invalid". How do you implement this without storing every JWT?
   (Hint: store refresh-token jti in Redis with TTL, and rotate.)

3. The "wrong-type token" case: a refresh token used as access
   should be rejected. Where in the dep chain is this caught?

4. Admin sessions vs JWT: completely separate paths. What primitive
   protects against confused deputy (admin session token sent as
   JWT bearer or vice versa)?

5. The "auto-create user on first OTP verify" behaviour: when does
   it happen? What Accept-Language is captured? What if email is
   later added — uniqueness is enforced.

6. The 5-attempt OTP lockout: is it on the OTP row (max_attempts) or
   on the phone (Redis counter)? Both? Per BACKEND §14.1, it's on
   the OTP row — but a brute-forcer can request a new OTP. Hence
   the rate limit on REQUESTS. Confirm this is correct.

7. Address default-handling: enforced at DB via generated column
   (BACKEND §6.5). What does the service do when SET DEFAULT is
   called on a new address while another is default? (Answer: clear
   the old one in the same transaction. Code it.)

8. The phone-change flow is **deferred to Phase 1.5** per
   PRODUCT §17.3 — for MVP, contact support. Don't build it.
   Document this in DECISION_LOG.

Sub-agents (recommended):
  Agent A: Spawn with mission "Read every section of BACKEND §14
           and produce a detailed sequence diagram (in text/ASCII)
           for OTP request, OTP verify, token refresh, and admin
           login. Identify every Redis key and DB write."
  Agent B: Spawn with mission "Survey all PRODUCT_BLUEPRINT auth
           edge cases (§17.3) and derive a test matrix: case →
           expected behaviour → which test file → priority."

After agents return, synthesise. Then TodoWrite plan with 14–20
items. Plan in chat. Wait for approval.

────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION GUIDANCE

- Models in app/domain/identity/models.py. Use the GUID type from
  Phase 2 for users.id. admin_users.id is BigInteger. admin_sessions.id
  is GUID (per PHARMACY §4.5).

- For user_addresses default-uniqueness, use a generated column trick
  (BACKEND §6.5). The migration has a manual op.execute for the
  generated column since Alembic's autogen handles Computed in 1.13+
  but emits non-MySQL-friendly SQL — verify and adjust.

- Repositories: small, intent-named methods. No commits inside.

- Services constructed via app/api/deps.py factories. Add factories
  for OtpService, AuthService, AccountService, AdminAuthService.

- OtpService.request_code:
     1. Rate-limit per phone AND per IP (two hits). If either fails,
        raise RateLimitExceededError.
     2. Generate 6-digit code with secrets.choice.
     3. HMAC-SHA256 hash with pepper.
     4. Insert otp_codes row (5-min TTL).
     5. Enqueue 'send_sms' ARQ job — but the queue is empty in
        Phase 4. Use a pluggable interface that no-ops in Phase 4
        and is wired to ARQ in Phase 11. Suggestion: a SmsQueue
        protocol, with an InProcessLogQueue fake for now.

- OtpService.verify_and_issue_tokens:
     1. Find active OTP for phone (most recent, not consumed, not
        expired).
     2. If not found: InvalidOTPError("not_found_or_expired").
     3. If attempts >= max: InvalidOTPError("too_many_attempts").
     4. Verify code with constant-time compare. On miss: increment
        attempts, raise.
     5. Mark consumed.
     6. Find or create user by phone (auto-create with
        is_phone_verified=True, preferred_language from header).
     7. Issue token pair, store refresh jti in Redis with TTL.

- Refresh:
     1. Decode refresh JWT, verify type=refresh.
     2. Look up jti in Redis; if missing → 401.
     3. Issue new pair. Delete old jti. Store new jti.

- Logout: revoke refresh jti.

- get_current_user: per BACKEND §14.3 verbatim. Reject if user
  inactive, deleted, or wrong token kind.

- AdminAuthService.login_with_password:
     1. Look up admin by email.
     2. If locked_until > now → 403 with reason.
     3. Verify password. On miss: increment failed_login_count;
        if reaches 5, set locked_until=now+15min.
     4. If MFA enabled, require TOTP code.
     5. Generate session token (secrets.token_urlsafe(32)).
        Store hash, expiry per settings.
     6. Set HttpOnly Secure SameSite=Lax cookie 'admin_session'.

- get_current_admin: read cookie, look up by token_hash, check
  expiry and not revoked, attach admin_user.

- require_role(*allowed): per BACKEND §14.5.

- require_branch_access: per BACKEND §14.5.

- Use copy keys from PRODUCT §21 for any user-facing string returned
  in errors. Errors carry a `code` (machine-readable) and `message`
  (resolved via i18n in the route, or untranslated for MVP — pick
  one; backend convention §15 uses untranslated server-side and lets
  the frontend translate by code).

  Decision: server returns `code` only; frontend resolves message.
  Document in DECISION_LOG.

- Migration drops the ping table from Phase 2 in the same migration
  that creates identity tables — small, single operation per BACKEND
  §9.5 ("one logical change per migration"). Actually: drop ping in
  its own preceding micro-migration. Two migrations in this phase is
  fine.

────────────────────────────────────────────────────────────────────────────
TEST EXPECTATIONS — DO NOT SKIMP

Unit tests (services with mocked repos):
  - test_otp_service_request: success, rate-limit phone, rate-limit
    IP, multiple OTPs in window allowed up to limit
  - test_otp_service_verify: success, expired, max attempts, wrong
    code increments, consumed once
  - test_auth_service_refresh: success rotates jti, missing jti
    rejected, expired refresh rejected
  - test_admin_auth_service: success, wrong password increments
    counter, lockout at 5, MFA required path

Repository tests (real DB):
  - user creation enforces phone uniqueness
  - address default-uniqueness enforced (try to insert two defaults
    for one user; second fails)
  - otp create + get_active works; consumed/expired filtered out

E2E tests (httpx against the app):
  - test_otp_full_flow: request → verify → /me succeeds with token
  - test_otp_rate_limited: 4th request in 15 min returns 429
  - test_otp_wrong_code: returns 401 with code=invalid_otp
  - test_refresh_rotation: old refresh becomes 401 after refresh
  - test_logout_revokes_refresh
  - test_addresses_crud: full lifecycle, default toggle works
  - test_admin_login_success: returns set-cookie; subsequent
    /admin/auth/me returns admin
  - test_admin_login_lockout: 5 failures locks for 15 min
  - test_admin_session_revoked: logout clears
  - test_role_required: pharmacist hitting super-admin endpoint → 403
  - test_branch_access: branch_manager from branch 1 hitting branch 2
    endpoint → 403

────────────────────────────────────────────────────────────────────────────
OUT OF SCOPE

  - Phone change flow (Phase 1.5)
  - SMS actually sending (Phase 10) — use the no-op queue
  - TOTP enrollment UI (we just verify the secret if set)
  - Customer email verification (no flow)
  - Account deletion / right-to-be-forgotten (Phase 2 of product)

────────────────────────────────────────────────────────────────────────────
DEFINITION OF DONE

  [ ] All identity models exist and migrate cleanly
  [ ] Ping table is dropped
  [ ] Repositories, services, schemas, deps, routes per spec
  [ ] All listed tests pass
  [ ] OPEN_QUESTIONS resolved or updated for any new ambiguities
  [ ] BACKEND §27 + PRODUCT §26 checklists pass

────────────────────────────────────────────────────────────────────────────
HAND-OFF

  1. Update BUILD_PROGRESS, CHANGELOG, DECISION_LOG.
  2. Manually exercise the flow with curl: request OTP, find the
     code in the application log (since SMS no-ops), verify, hit
     /me. Capture the curl session in BUILD_PROGRESS.md as a
     "smoke test recipe" for the next phase.
  3. Post chat summary: what's now possible, what's tested, what
     deferred to other phases.
  4. STOP.
```


---

## Phase 5 — Catalog Domain & Admin Catalog API

**Goal.** Catalog domain end-to-end on the admin side: manufacturers, active ingredients, categories, symptoms, products, translations, images, M:N tables. Admin endpoints to CRUD all of it. Bulk import via CSV/XLSX as a background job stub (worker proper in Phase 11). Image upload pipeline scaffolded with a synchronous fallback for MVP.

**Input.** Phase 4 done. `/me` works.
**Output.** A super_admin or content_editor can create the entire catalog via API. Customer-facing catalog reads come in Phase 7.
**Estimated session length.** 3–4 hours (consider splitting at the seam: models+repos first, services+API second).

### The prompt

```
You are a senior backend engineer implementing the catalog domain for the
Pharmacy Platform. Identity (Phase 4) is complete and authenticated admin
sessions work.

────────────────────────────────────────────────────────────────────────────
SPECS TO RE-READ

Required:
  - PRODUCT_BLUEPRINT §5    (Pharmacy domain primer — ALL of it; this is
                             where you learn that "active ingredient" is
                             the central concept)
  - PRODUCT_BLUEPRINT §8.5  (Admin catalog features F-ADM-CAT-001..004)
  - PRODUCT_BLUEPRINT §13   (Catalog content standards)
  - PRODUCT_BLUEPRINT §17.4 (Catalog edge cases)
  - PRODUCT_BLUEPRINT §19.5 (Permissions matrix — content_editor scope)
  - PHARMACY_BLUEPRINT §5   (Catalog schema — manufacturers, categories,
                             products, translations, images, M:N tables)
  - BACKEND_BLUEPRINT §8.2..§8.4 (model patterns, FULLTEXT scaffold,
                                  loading strategies)

────────────────────────────────────────────────────────────────────────────
MISSION

Models + migration:
  - manufacturers
  - active_ingredients + active_ingredient_translations
  - categories + category_translations
  - symptoms + symptom_translations
  - products + product_translations + product_images
  - product_active_ingredients (M:N with dosage)
  - product_symptoms (M:N)

Migration includes:
  - All tables with correct charset/collation
  - FULLTEXT index on product_translations(name, short_description,
    description) WITH PARSER ngram (manual op.execute, BACKEND §9.4)
  - "One primary image per product" via generated-column trick
    (BACKEND §6.5)

Repositories: one per aggregate root, per BACKEND §11.

Services:
  - CatalogAdminService:
      - manufacturers CRUD
      - active_ingredients CRUD + translations
      - categories CRUD + translations + tree-aware ops
      - symptoms CRUD + translations
      - products CRUD: includes translations, M:N ingredient/dose
        and symptoms in one transaction
      - bulk operations: bulk price update, bulk active toggle
  - ProductImageService:
      - accept upload, persist temp file, enqueue process_image_upload
        job (Phase 11), return image record
      - For Phase 5, provide a synchronous fallback that does the
        resize inline using Pillow (slow but works) — Phase 11
        replaces with worker
  - ProductImportService:
      - parse CSV/XLSX
      - dry-run validation: returns row-level errors as a structured
        list
      - apply: idempotent by SKU, updates existing, inserts new,
        never deletes
      - For Phase 5, runs synchronously (small files); Phase 11 wraps
        in ARQ job for real
  - SlugService: generate slug from RU name via transliteration

Schemas (per BACKEND §10):
  - All Create/Update/Read for each entity above
  - ProductCreate carries translations[], images? (no — separate
    upload endpoint), ingredients[] with dose, symptoms[] by id

Admin API (app/api/admin_v1/...):
  - manufacturers.py — full CRUD
  - active_ingredients.py — full CRUD + translations
  - categories.py — full CRUD + tree, prevent delete-with-children/
    products
  - symptoms.py — full CRUD + translations
  - products.py — full CRUD, separate endpoints for images upload,
    bulk import dry-run + apply, bulk price update
  - All scoped via require_role for super_admin or content_editor;
    branch_manager only allowed price updates and is_active toggles
    (PRODUCT §19.5)

────────────────────────────────────────────────────────────────────────────
PLAN FIRST — DEEP THINKING REQUIRED

Apply deep thinking on:

1. Product creation as a single transaction: a product has 0..n
   translations, 1..n active ingredients with doses, 0..n symptoms,
   0..n images. The endpoint accepts all but images in one POST. How
   do you ensure atomicity? Where do default values come from? What
   happens if a referenced category_id is invalid?

2. The "one primary image per product" generated column: must work
   on MySQL 8 with persisted=True. Test that two images can't both
   be is_primary=true. The migration must apply cleanly on a fresh
   container and on an existing one (idempotent enough).

3. FULLTEXT setup: must run AFTER table creation in the migration.
   Use op.execute with raw SQL. Add a downgrade that drops it.
   ngram_token_size is a server variable (set in docker-compose).
   Note in DECISION_LOG that token_size=2 is the choice for MVP.

4. Slug generation: Russian → Latin transliteration is non-trivial.
   Use a library (python-slugify with custom transliteration map for
   Cyrillic). On collision, append -2, -3, … (like Wordpress).
   What about KY-only names? Assume Russian fallback exists per
   PRODUCT §13.4.

5. Bulk import idempotency: "by SKU" means SKU is the key. What if
   the same row appears twice in one file? (Reject the file at
   validation.) What if a translation is malformed? (Row-level
   error.) What if two languages say the same thing? (Allowed.)

6. Bulk import column contract: document it inline in the admin UI
   docs (later) but the code should accept BOTH CSV and XLSX with
   the same column set. Define column names exactly:
     sku, barcode, slug, manufacturer, category_path, form,
     pack_size_label, pack_quantity, pack_unit, requires_prescription,
     min_age, max_per_order, weight_grams, requires_cold_chain,
     storage_temp_min_c, storage_temp_max_c, is_active, is_featured,
     name_ru, name_ky, name_en, short_description_ru, ...,
     description_ru, ..., active_ingredients (semicolon-separated:
     "Paracetamol:500:mg;Caffeine:50:mg"), symptoms (semicolon-
     separated slugs)
   Lock this contract now. Document in BUILD_PROGRESS as the spec
   referenced by the import service.

7. Image processing tradeoff: synchronous Pillow resize blocks the
   request for ~1–3 seconds for a typical product image. For Phase 5,
   acceptable. Write the code so it can be lifted into the worker
   in Phase 11 by extracting a process_image(path, sizes) function
   that the worker calls.

Sub-agents:
  Agent A: Audit PHARMACY §5 and produce a matrix of every catalog
           table → SQLAlchemy model fields → MySQL specifics
           (charset, indexes, FULLTEXT, generated columns, CHECKs).
  Agent B: Read PRODUCT §5 (domain primer) AND §13 (content
           standards) AND draft a sample product fixture (full
           Panadol entry with RU/KY/EN translations, paracetamol
           ingredient, 'headache' and 'fever' symptoms, two
           images) for use in tests.

TodoWrite plan with 18–25 items. Plan in chat. Wait for approval.

────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION GUIDANCE

- Follow BACKEND §8.2 for the Product model template precisely.

- Use selectinload for translations and images when loading lists;
  joinedload for manufacturer when loading a product detail.

- For tree categories: keep adjacency list (parent_id) for MVP.
  Recursive CTE only when you actually need the tree on a request
  (rare for admin, where you list categories paginated).

- Permissions:
     - super_admin: all CRUD
     - content_editor: all CRUD on catalog (no inventory or orders)
     - branch_manager: only price update for products in their
       branch via Phase 6 endpoints (NOT in this phase)
     - pharmacist: read-only on catalog

- Image endpoints:
     - POST /admin/products/:id/images (multipart) → returns image record
     - DELETE /admin/products/:id/images/:image_id
     - PATCH /admin/products/:id/images/:image_id (set is_primary,
       reorder)

- Bulk import endpoints:
     - POST /admin/products/import/dry-run (multipart) → returns
       structured errors + summary (n_create, n_update, n_skip)
     - POST /admin/products/import/apply (multipart, idempotency-key
       header) → applies; for Phase 5 runs synchronously up to 500
       rows; >500 rows returns 413 with "use bulk import worker —
       Phase 11" (TODO marker)

- Translation completeness rule (PRODUCT §13.4): a product with no
  RU translation is hidden from storefront. Enforced at customer
  read layer (Phase 7), but mark in admin UI as a warning when
  creating without RU. For Phase 5: validate in service that at
  least one translation is present, RU recommended.

- Active ingredient + dose: the M:N table has dose. Endpoint accepts
  list of {ingredient_id, dose_amount, dose_unit}. Validate dose_unit
  is in the enum.

- Symptom mapping: by slug or id. Validate existence in service.

- Audit: every admin mutation writes admin_audit_log. For Phase 5,
  introduce the AdminAuditLog model + write helper but the table
  itself is created in Phase 9 — no, contradicts. Actually:
  reconsider — admin_audit_log lives in ops domain (Phase 9). Two
  options:
     a) Add an admin_audit_log table NOW (Phase 5) so every mutation
        is logged from day one. Phase 9 just adds the viewer UI.
     b) Buffer audit events to a queue/log file in Phase 5 and
        replay them when the table arrives in Phase 9.
   Decision: (a). Add admin_audit_log table in this phase's
   migration. Update DECISION_LOG accordingly.

────────────────────────────────────────────────────────────────────────────
TEST EXPECTATIONS

Repository:
  - product create with translations, ingredients, symptoms in one
    transaction
  - "one primary image" constraint enforced
  - FULLTEXT search returns expected hits (basic sanity: insert
    "Парацетамол" + "Аспирин"; search for "пара" returns the first)

Service:
  - bulk import dry-run: malformed rows reported, valid rows pass
  - bulk import apply: idempotent (re-apply same file → no diffs)
  - slug uniqueness: collision adds suffix
  - cannot delete a category with children
  - cannot delete a manufacturer with active products

E2E:
  - content_editor creates manufacturer/category/product end-to-end
  - pharmacist gets 403 on POST /admin/products
  - branch_manager gets 403 on POST /admin/products
  - bulk import dry-run returns errors for malformed CSV
  - product detail GET returns nested translations and images
  - audit log row exists after every mutation

────────────────────────────────────────────────────────────────────────────
OUT OF SCOPE

  - Customer-facing catalog reads (Phase 7)
  - Search ranking refinements (Phase 7)
  - Image worker pipeline (Phase 11)
  - Bulk import worker for >500 rows (Phase 11)
  - Branch-specific pricing (Phase 6)

────────────────────────────────────────────────────────────────────────────
DEFINITION OF DONE

  [ ] All catalog tables migrated; FULLTEXT index in place
  [ ] All admin catalog endpoints working with correct RBAC
  [ ] Bulk import dry-run + apply work for ≤ 500 rows
  [ ] Image upload + primary toggle works
  [ ] admin_audit_log writes on every mutation
  [ ] Tests: repository, service, E2E — all pass
  [ ] BACKEND §27 + PRODUCT §26 checklists pass

────────────────────────────────────────────────────────────────────────────
HAND-OFF

  1. Seed a small dev catalog: 1 manufacturer, 3 categories, 5
     active ingredients, 5 symptoms, 10 products with full
     translations and images. Commit fixtures under
     dev/fixtures/catalog/.
  2. Update BUILD_PROGRESS, CHANGELOG, DECISION_LOG, OPEN_QUESTIONS.
  3. Post chat summary; note any catalog spec gaps surfaced.
  4. STOP.
```

---

## Phase 6 — Inventory Domain & Admin Inventory API

**Goal.** Branches, suppliers, branch_products (price + cached stock), inventory_batches (source of truth), stock_movements (audit trail). Admin endpoints to receive stock, adjust, view near-expiry and low-stock. Service-layer FEFO selection function (used by Phase 8).

**Input.** Phase 5 done. Catalog exists.
**Output.** A pharmacist can receive a batch, system updates stock truth, near-expiry and low-stock dashboards work.
**Estimated session length.** 3 hours.

### The prompt

```
You are a senior backend engineer building inventory for the Pharmacy
Platform. Phases 1–5 are complete; the catalog is populated.

This phase's correctness is operationally critical. Stock numbers people
trust are the foundation of the business. Take it seriously.

────────────────────────────────────────────────────────────────────────────
SPECS TO RE-READ

Required:
  - PRODUCT_BLUEPRINT §5.5  (Expiry and FEFO)
  - PRODUCT_BLUEPRINT §5.6  (Batch and recall)
  - PRODUCT_BLUEPRINT §7.4  (Journey J-04 — receiving)
  - PRODUCT_BLUEPRINT §8.6  (Admin inventory features F-ADM-INV-001..004)
  - PRODUCT_BLUEPRINT §10   (Inventory & stock rules — ALL)
  - PRODUCT_BLUEPRINT §17.5 (Inventory edge cases)
  - PHARMACY_BLUEPRINT §6   (Branches & inventory schema)
  - PHARMACY_BLUEPRINT §11.4 (Place-order transaction — preview; you'll
                              write FEFO selection here)
  - BACKEND_BLUEPRINT §6.5, §11.2 (FEFO repository pattern)

────────────────────────────────────────────────────────────────────────────
MISSION

Models + migration:
  - branches
  - suppliers
  - branch_products (PK = (branch_id, product_id), with total_quantity,
    reserved_quantity, low_stock_threshold)
  - inventory_batches (UNIQUE(branch_id, product_id, batch_number))
  - stock_movements (append-only)

Repositories:
  - BranchRepository, SupplierRepository
  - BranchProductRepository (get/upsert, increment_reserved,
    increment_total, list_low_stock, get_available_quantity)
  - InventoryBatchRepository (add_batch, list_for_fefo_locked,
    list_near_expiry, list_expired)
  - StockMovementRepository (append-only writes; range queries)

Services:
  - InventoryService:
      - receive_batch (creates batch, increments total_quantity,
        writes stock_movements 'received')
      - adjust_batch (writes stock_movements 'damaged' or 'adjusted'
        with reason; updates batch and cached total)
      - allocate_for_order(branch_id, product_id, qty) -> list of
        (batch_id, batch_number, expiry_date, qty) using FEFO
      - reserve(allocations, order_id) — writes 'reserved' movements,
        increments branch_products.reserved_quantity
      - convert_reservation_to_sold(order_id) — flips reserved →
        sold, decrements total_quantity
      - release_reservations(order_id) — decrements reserved
      - reconcile_branch_product(branch_id, product_id) — recomputes
        total_quantity from non-expired batches (used by nightly job)
      - list_near_expiry(branch_id, days) and list_low_stock(branch_id)

Admin API (app/api/admin_v1/inventory.py):
  - POST /admin/branches/:id/inventory/batches (receive)
  - PATCH /admin/inventory/batches/:id (adjust, with reason)
  - GET /admin/branches/:id/inventory (search, filters: low_stock,
    expiring, query)
  - GET /admin/inventory/movements (audit, with filters)
  - GET /admin/branches/:id/reports/near-expiry?days=30|60|90
  - GET /admin/branches/:id/reports/low-stock

────────────────────────────────────────────────────────────────────────────
PLAN FIRST — DEEP THINKING ON CONCURRENCY

This phase's hardest problem is concurrent stock allocation. Apply
deep thinking on:

1. The FEFO query uses FOR UPDATE SKIP LOCKED. Walk through what
   happens when two place-order transactions arrive at the same
   millisecond for the same product:
     - T1 selects batch A (10 units) FOR UPDATE SKIP LOCKED
     - T2 selects batch A (gets nothing — locked); selects batch B
     - T1 commits, T2 commits
     - Result: A is depleted by T1; B by T2. No oversell.
   Verify this with an actual concurrent test (asyncio.gather of
   two reservations). If you skip this test, you don't have FEFO
   correctness — you have FEFO hopefulness.

2. The cached total_quantity vs source-of-truth batches: every
   write that changes batches must also update branch_products.
   Document the invariant clearly. The reconciliation job (Phase 11)
   is the safety net, not the primary mechanism.

3. The 7-day hard block on expiry: where is it enforced?
     - In allocate_for_order: filter expiry_date > today + 7 days
     - In total_quantity reconciliation: same filter
     - In the daily expire_batches job (Phase 11): marks recent
       expirations
   Choose: enforce in the FEFO query (BACKEND §6.5 hints at this).
   Add a CHECK constraint? No — the constraint depends on "today"
   which moves. Enforce in queries.

4. Receiving rules:
     - Hard block: expiry ≤ today + 7 days unless override flag (rare,
       receiving error). Document this in DECISION_LOG.
     - Soft warn: expiry ≤ today + 60 days. Service returns a flag
       in response so admin UI can highlight.
     - Cost price required.
     - Same batch_number arriving again for same product+branch:
       error "batch already received" — admin uses adjust, not
       another receive.

5. The "auto-released after 24h pending" and "30-min for card payment"
   rules (PRODUCT §10.6) — implement the release logic now even
   though the scheduler is in Phase 11. Service has
   release_pending_orders(older_than_minutes) — Phase 11 just
   schedules it.

6. branch_products row must exist before stock can be received. Two
   options:
     a) Create lazily on first receive (auto-insert with default
        price = 0, is_available=false until admin sets price)
     b) Require explicit "list product at branch" admin action
   Decision: (a) — pragmatic. But mark with a flag pending-pricing
   so the storefront filters them out. Document in DECISION_LOG.

Sub-agents:
  Agent A: Read BACKEND §6.4 + §11.2 carefully and produce the exact
           SQLAlchemy code for the FEFO selection query, including
           SKIP LOCKED. Run it through your understanding —
           confirm the ORDER BY tie-break and the batch filtering
           predicate match the spec.
  Agent B: Audit the stock_movements CHECK constraint
           (PHARMACY §6.5). Verify that every movement_type emits
           the right sign. Produce a test matrix:
           type x quantity_change_sign x expected_outcome.

TodoWrite plan with 16–22 items. Plan in chat. Wait for approval.

────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION GUIDANCE

- Models per PHARMACY §6 with MySQL adaptations:
     - branch_products: composite PK (branch_id, product_id)
     - inventory_batches: BigInteger PK
     - stock_movements: BigInteger PK; CHECK constraints per
       PHARMACY §6.5 (movement type vs sign of quantity_change)

- Service methods MUST be transactional. allocate_for_order +
  reserve must be a single DB round-trip ideally; in any case,
  same transaction.

- Auditability: every admin action via inventory writes
  admin_audit_log with diff. Stock movements ARE the audit trail
  for stock changes; admin_audit_log captures the admin action that
  triggered it.

- For PHARMACY §11.4 (place-order transaction), don't write the
  full place_order here — that's Phase 8. But the building blocks
  (allocate_for_order, reserve) live here. Phase 8 calls them.

- API surface notes:
     - Receiving form has many fields; ensure good error messages
       (PRODUCT §21 doesn't cover admin copy — use plain English
       at admin tier; document in DECISION_LOG that admin UI is EN-
       primary for now).
     - Reports return rows suitable for both UI and CSV export.
       Add ?format=csv that streams via StreamingResponse.

────────────────────────────────────────────────────────────────────────────
TEST EXPECTATIONS

Critical:
  - test_fefo_concurrent: spawn two coroutines that simultaneously
    allocate the same product. Assert no oversell, no deadlock, no
    duplicate batch use. Run this in a loop 100x in CI to catch
    flakes.

Repository / service:
  - receive_batch happy path; cost_price required; same batch
    twice rejected
  - 7-day expiry block in allocate_for_order
  - reservation→sold→cancel flows update both total and reserved
  - reconcile_branch_product detects drift and corrects
  - low-stock report respects threshold
  - near-expiry report respects 30/60/90 windows

E2E:
  - pharmacist receives a batch; total_quantity increments
  - pharmacist adjusts a batch with reason; movement recorded;
    total decremented
  - branch_manager from another branch is forbidden
  - content_editor cannot touch inventory (403)
  - reports return correct rows

────────────────────────────────────────────────────────────────────────────
OUT OF SCOPE

  - place_order (Phase 8)
  - Scheduled jobs (Phase 11)
  - Inter-branch transfers (Phase 2 of product roadmap)
  - Recall workflow (Phase 2)
  - Cold-chain summer surcharge (Phase 2)

────────────────────────────────────────────────────────────────────────────
DEFINITION OF DONE

  [ ] Tables migrated with proper constraints
  [ ] FEFO concurrent-allocation test passes 100x
  [ ] Receive / adjust / reports endpoints work with RBAC
  [ ] Admin audit log captures all mutations
  [ ] Stock movements are append-only and balance correctly
  [ ] Tests all pass; checklist tickets ticked

────────────────────────────────────────────────────────────────────────────
HAND-OFF

Same as prior phases. Demonstrate end-to-end: receive 100 units of
Panadol, query stock, allocate 10 (mock-as-if for Phase 8), confirm
remaining = 90. Capture in BUILD_PROGRESS.
```

---

## Phase 7 — Customer Discovery (Browse & Search)

**Goal.** Customer-facing catalog. Categories tree, products listing with filters, product detail page, symptom browse, search with FULLTEXT + ranking, autocomplete suggestions, substitutes block, out-of-stock behaviour. Caching for hot reads. No cart yet.

**Input.** Phase 6 done. Inventory + catalog ready.
**Output.** A guest can browse and search the storefront end-to-end.
**Estimated session length.** 2.5–3 hours.

### The prompt

```
You are a senior backend engineer building customer discovery for the
Pharmacy Platform. Phases 1–6 are complete.

This is the highest-traffic surface area in the product. Performance,
caching, and search quality matter. Apply senior judgement.

────────────────────────────────────────────────────────────────────────────
SPECS TO RE-READ

Required:
  - PRODUCT_BLUEPRINT §6   (Product pillars — find-it-fast)
  - PRODUCT_BLUEPRINT §7.1, §7.2 (J-01, J-02 — discovery flows)
  - PRODUCT_BLUEPRINT §8.2 (Catalog & discovery features F-CAT-001..008)
  - PRODUCT_BLUEPRINT §12  (Search & discovery behaviour — ranking,
                            synonyms, must-not-do)
  - PRODUCT_BLUEPRINT §17.4 (Catalog edge cases relevant here)
  - PHARMACY_BLUEPRINT §11.1, §11.2 (storefront query patterns)
  - BACKEND_BLUEPRINT §17.4 (Stale-while-revalidate)
  - BACKEND_BLUEPRINT §18  (Caching keys, TTLs)

────────────────────────────────────────────────────────────────────────────
MISSION

Customer endpoints (no auth required):
  - GET /api/v1/categories                     (full tree, cached)
  - GET /api/v1/categories/:slug               (single + breadcrumb)
  - GET /api/v1/categories/:slug/products      (paginated)
  - GET /api/v1/symptoms                       (list)
  - GET /api/v1/symptoms/:slug/products
  - GET /api/v1/products/:slug                 (detail)
  - GET /api/v1/products/:slug/related         (substitutes)
  - GET /api/v1/search?q=&lang=&page=
  - GET /api/v1/search/suggest?q=&lang=
  - GET /api/v1/branches                       (for footer / about)

Service layer:
  - CatalogService (read-only customer-facing):
      - get_categories_tree(lang) — cached 1h
      - get_category_with_products(slug, lang, branch_id, filters,
        page, page_size)
      - get_product_detail(slug, lang, branch_id) — cached 5m;
        invalidates on product/translation/image/branch_product
        update
      - list_substitutes(product_id, branch_id, lang) — same active
        ingredient + dose, in stock, ≤ 4 results, ordered by price
      - get_symptom_with_products(slug, lang, branch_id, filters,
        page)
  - SearchService:
      - search(q, lang, branch_id, filters, page) — composite ranking
        (BACKEND §10.1 had Postgres examples; for MySQL use FULLTEXT
        + LIKE prefix + ngram score; PRODUCT §12.2 ranking order)
      - suggest(q, lang) — short list of products + categories +
        symptoms; cached 60s; logs to search_log
      - synonym expansion via app/i18n/synonyms.json (admin-edited
        in Phase 9; for Phase 7 we ship a starter set)

────────────────────────────────────────────────────────────────────────────
PLAN FIRST — DEEP THINKING ON SEARCH QUALITY

Search is the feature most likely to disappoint at MVP. Apply deep
thinking on:

1. The MySQL ngram parser query syntax: MATCH(...) AGAINST (... IN
   BOOLEAN MODE). What's the score, and how does it combine with
   our prefix and exact-name boosts?

2. The composite ranking from PRODUCT §12.2:
     1. Exact name match
     2. Prefix match
     3. FULLTEXT match (name + description)
     4. Active ingredient match
     5. Symptom tag match
     6. Manufacturer match
   How do you combine these into a single ORDER BY? Suggestion:
   compute a numeric score per row (CASE expressions + score *
   weight) and order by it. Sketch the SQL on paper before coding.

3. The synonym expansion: PRODUCT §12.4 has examples. Where does
   the expansion happen — in the request layer (broadcast queries)
   or in the index? For MVP, expand in application: if query word
   matches a synonym key, add the synonym values to the boolean
   query as OR terms. Document this design.

4. Test queries from PRODUCT §12.1 — these are the QA gates:
     парацетамол, пара, парацитамол, paracetamol, от головы,
     жаропонижающее, панадол, головная боль, температура, анальгин
   Each MUST return Paracetamol products as the top result with the
   right test data loaded. Build these as automated tests.

5. The "in stock only" default filter: customers default to seeing
   in-stock products. They can toggle off. branch_products.total_qty
   - reserved_qty > 0 is the predicate.

6. Caching strategy:
     - Categories tree: 1h, invalidated on category/translation
       mutations (Phase 5 service hooks already exist? — verify and
       extend)
     - Product detail: 5m, key = product_id + lang
     - Search suggestions: 60s, key = q + lang
     - Search results: NOT cached (too many permutations, low hit
       rate)
   Implement cache invalidation hooks NOW: every mutation in
   Phase 5/6 services should call cache.invalidate appropriately.
   If those hooks don't exist yet, add them.

7. Out-of-stock UX: PRODUCT §F-CAT-008. Out-of-stock products are
   listed with disabled CTA and substitutes block prominently.
   The API returns is_in_stock + substitutes — frontend renders.

Sub-agents:
  Agent A: Web search current best practices for MySQL FULLTEXT
           with ngram parser for Cyrillic. Confirm
           ngram_token_size=2 vs 3, IN BOOLEAN MODE syntax,
           score formula. Produce a brief.
  Agent B: Read PRODUCT §21 search keys and PRODUCT §12 in
           parallel, derive a list of UI strings the API should
           return for empty states (search.no_results.title etc.).

TodoWrite plan with 14–18 items. Plan in chat. Wait for approval.

────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION GUIDANCE

- All customer endpoints support Accept-Language and resolve via
  app/core/i18n.py.

- Default branch_id: with one branch, derive it. Add a
  resolve_branch dependency that reads from request (cookie? query?).
  For MVP, hardcode branch_id=1 and document. Phase 2 of product
  roadmap adds branch selection.

- Category tree: build from flat list with two queries; assemble
  in Python. Cache the result.

- Product list: SELECT with JOIN to translation (lang or default
  fallback), JOIN to branch_products for stock + price, LEFT JOIN
  to primary image. Use selectinload for nested ingredients/symptoms
  on the detail page only (not on lists).

- Substitutes query (per PRODUCT §F-CAT-007): same primary active
  ingredient (the first by sort? the highest-dose? — design choice;
  pick "the one with the highest dose" as primary, document) + same
  dose. Fall back to same ingredient (different dose) labelled
  accordingly. Excludes current product. Limit 4. In stock only.

- Search:
     - Validate q is at least 2 characters.
     - Expand synonyms.
     - Build boolean MATCH query with + for required terms, |
       for synonyms.
     - Combine MATCH score with prefix/exact-name boost.
     - Filter by is_active, deleted_at IS NULL,
       (in_stock_only ? available > 0 : true).
     - Limit + offset.
     - Log to search_log (results_count, lang, user_id when
       authenticated).

- Suggest endpoint:
     - At least 2 chars; debounced client-side.
     - Returns: 4 products (with thumbnail + name + price + slug),
       2 categories, 2 symptoms.
     - Cached 60s.

- Synonym dictionary: app/i18n/synonyms_ru.json. Format:
     {
       "простуда": ["орви", "грипп"],
       "от головы": ["головная боль", "обезболивающее"],
       ...
     }
   Keys are lower-cased; matching is lower-cased.

────────────────────────────────────────────────────────────────────────────
TEST EXPECTATIONS

Search quality (these are the must-pass tests of this phase):
  Insert in test setup: paracetamol product (with translations,
  active ingredient, headache+fever symptoms), aspirin product,
  ibuprofen product. Then:
  - test_search_exact_ru: "парацетамол" → paracetamol first
  - test_search_prefix_ru: "пара" → paracetamol first
  - test_search_typo_ru: "парацитамол" → paracetamol in top 3
  - test_search_latin: "paracetamol" → paracetamol first
  - test_search_symptom: "головная боль" → paracetamol present
  - test_search_brand_synonym: "анальгин" → metamizole-containing
    product first (skip if not in fixtures; assert non-empty)
  - test_search_zero_results: "asdfqwer" → empty + suggestions

Caching:
  - test_categories_tree_cached: hit DB once, second call hits cache
  - test_product_detail_cache_invalidates_on_update

Behaviour:
  - test_out_of_stock_listed_but_disabled: product with available=0
    appears in category page but with is_in_stock=false
  - test_substitutes: paracetamol product detail returns 2-4
    substitutes
  - test_in_stock_filter_default: ?in_stock_only=true (default)
    returns only available > 0

Performance (informational, not gating):
  - p95 of category-page list ≤ 200ms in test env
  - p95 of search ≤ 250ms in test env

────────────────────────────────────────────────────────────────────────────
OUT OF SCOPE

  - Cart (Phase 8)
  - Personalised "you may also like" (Phase 2 product)
  - Reviews (never per PRODUCT §3.1)
  - Filtering by exact attributes JSON (Phase 2)
  - Notify-when-available (Phase 2)

────────────────────────────────────────────────────────────────────────────
DEFINITION OF DONE

  [ ] All customer endpoints return correct shape
  [ ] All search test queries from PRODUCT §12.1 pass
  [ ] Caching works with invalidation hooks from Phase 5/6
  [ ] Out-of-stock listed and substitutes returned
  [ ] BACKEND §27 + PRODUCT §26 checklists pass
  [ ] OpenAPI docs updated (FastAPI generates; review for clarity)

────────────────────────────────────────────────────────────────────────────
HAND-OFF

Same. Capture in BUILD_PROGRESS the exact curl commands for each
search test query, with expected results.
```

---

## Phase 8 — Cart, Checkout & Place-Order (FEFO)

**Goal.** The most critical phase. Customer cart, checkout flow, the place-order transaction with FEFO allocation, idempotency, customer order history.

**Input.** Phase 7 done. Customers can browse.
**Output.** A customer can place an order end-to-end. Stock is correctly reserved and tracked.
**Estimated session length.** 3–4 hours. Take it slowly.

### The prompt

```
You are a senior backend engineer building cart, checkout, and the place-
order transaction for the Pharmacy Platform. This is the heart of the
business. Concurrency mistakes here cause oversells, lost orders, or
corrupt stock. Apply maximum care.

────────────────────────────────────────────────────────────────────────────
SPECS TO RE-READ — MULTIPLE TIMES

Required (read each at least twice):
  - PRODUCT_BLUEPRINT §7.1, §7.2, §7.3 (J-01, J-02, J-03)
  - PRODUCT_BLUEPRINT §8.3, §8.4 (Cart, checkout, orders features)
  - PRODUCT_BLUEPRINT §9   (Order state machine — print this section)
  - PRODUCT_BLUEPRINT §10  (Inventory rules — esp. reservation lifecycle)
  - PRODUCT_BLUEPRINT §11  (Pricing & payment UX)
  - PRODUCT_BLUEPRINT §17.1, §17.2, §17.6 (cart, order, payment edges)
  - PRODUCT_BLUEPRINT §21  (Copy keys for cart/checkout/order)
  - PHARMACY_BLUEPRINT §7  (Cart, orders, payments schema)
  - PHARMACY_BLUEPRINT §11.3, §11.4 (cart and place-order query patterns)
  - BACKEND_BLUEPRINT §12.2 (PlaceOrderService template)
  - BACKEND_BLUEPRINT §21  (Idempotency)

────────────────────────────────────────────────────────────────────────────
MISSION

Models + migration:
  - carts, cart_items
  - orders, order_items, order_status_history
  (payments and deliveries tables are Phase 10 — but order has
   payment_status field; that field exists from this phase)

Repositories:
  - CartRepository, OrderRepository, OrderStatusHistoryRepository

Services:
  - CartService (get_or_create, add_item, update_qty, remove_item,
    clear, merge_guest_cart_into_user)
  - CheckoutService (quote — compute totals; place_order — the
    critical transaction)
  - OrderService customer-facing: list, get, cancel-by-customer

Customer API (app/api/v1/...):
  - GET /cart                          (current user's or guest's)
  - POST /cart/items                   {product_id, quantity}
  - PATCH /cart/items/:id              {quantity}
  - DELETE /cart/items/:id
  - POST /cart/clear
  - POST /checkout/quote               {address_id, delivery_method}
                                       → totals
  - POST /checkout/place               (Idempotency-Key required)
                                       {address_id, payment_method,
                                        delivery_method, recipient_*,
                                        notes}
                                       → {order_number,
                                          payment_redirect_url?}
  - GET /me/orders                     (cursor paginated)
  - GET /me/orders/:order_number       (full detail)
  - GET /me/orders/:order_number/status (lightweight polling endpoint)
  - POST /me/orders/:order_number/cancel
  - POST /me/orders/:order_number/reorder → adds to current cart

────────────────────────────────────────────────────────────────────────────
PLAN FIRST — APPLY MAXIMUM DEEP THINKING

This phase has more concurrency and edge cases than every other
combined. Before you write a line of code, walk through these:

1. THE PLACE-ORDER TRANSACTION:
   Read BACKEND §12.2 and PHARMACY §11.4 again. Sketch the steps
   in your own words. Then identify every place that can fail:

   - Cart was emptied by another tab between quote and place
   - Stock dropped below cart quantity between quote and place
   - Price changed between quote and place
   - User's address was deleted between quote and place
   - Payment method requires gateway, but gateway is down
   - The reservation succeeds but the order INSERT fails on
     UNIQUE(order_number)
   - The same Idempotency-Key arrives twice within milliseconds
   - Two devices (same user) try to place the same cart at once

   For each failure case, document the desired behaviour. THEN
   implement.

2. ISOLATION LEVEL:
   MySQL default is REPEATABLE READ. Will it suffice? Walk through:
     - Read available_quantity (T1: 10)
     - Read available_quantity (T2: 10)
     - Both decide they can fulfill 5
     - Both UPDATE inventory_batches with FOR UPDATE SKIP LOCKED →
       different batches lock for each → no conflict
     - Both UPDATE branch_products.reserved_quantity with row lock
       → second waits for first → second sees updated value when
       woken
   Confirm REPEATABLE READ + FOR UPDATE on the right rows is
   enough. If not, escalate to SERIALIZABLE for this transaction.

3. IDEMPOTENCY:
   Backend §21. The Idempotency-Key header is REQUIRED. Behaviour:
     - First call: stub key in Redis "processing", do the work,
       store the response under the key (24h TTL).
     - Concurrent duplicate: returns 409 if processing flag still
       set after a short timeout? — actually simpler: read-after-
       write. If we see a stub but no response, we wait briefly
       (200ms) and retry the lookup. If still no response, return
       409 (likely the first call crashed).
     - Repeated call after success: return stored response.
     - Repeated call with different body: return 409 idempotency_
       conflict.

4. CART EXPIRY AND MERGE:
   - Guest cart lives in carts table keyed by session_id, expires
     30 days
   - On login: merge guest cart into user cart (additive on same
     product, capped at max_per_order)
   - On expired cart access: return cart_expired error code

5. STOCK REVALIDATION (PRODUCT §F-CART-002):
   On click of "place order":
     - Re-read every cart item's available stock and current price
     - If any item's available < quantity → return 409 with details
     - If any price changed → return 409 with old/new
     - Customer must confirm changes (frontend resubmits)

6. RESERVATION TIMEOUT:
   - pending order > 24h → release (Phase 11 job)
   - card-payment pending order > 30 min unconfirmed → release
     (Phase 11 job)
   For Phase 8: write the methods, leave scheduling to Phase 11.

7. PAYMENT FLOW BRANCHING:
   - cash_on_delivery: order goes to pending; payment_status=pending
     until delivery; no gateway call
   - card_online (Phase 1.5 — but scaffold now):
       1. Create order with status=pending, payment_status=pending
       2. Reserve stock
       3. Call payment gateway (Phase 10 — for now, FakePayment
          returns redirect_url instantly)
       4. Return redirect_url to client
       5. Webhook later updates payment_status (Phase 10)

8. CANCEL BY CUSTOMER (PRODUCT §F-ORD-002):
   Allowed only if status ∈ {pending, confirmed}. Releases stock
   reservations. If paid by card, refund (manual for MVP — create
   a refund task; admin handles via gateway).

9. REORDER (PRODUCT §F-ACC-004):
   Adds previous order's items to current cart. Validates stock
   and prices. Out-of-stock items flagged but not blocked.
   If a product was deleted, snapshot name shown; user can remove.

Sub-agents:
  Agent A: Sketch the place-order transaction in pseudocode, then
           translate to actual SQLAlchemy async. Verify FOR UPDATE
           SKIP LOCKED is correctly placed. Surface any concerns
           about SQLAlchemy's lazy-load behaviour mid-transaction.
  Agent B: Build a concurrency test plan: pairwise scenarios that
           must work (two orders different products, two orders
           same product different batches, two orders same product
           same batch, etc.). Each gets a test.

TodoWrite plan with 20–28 items. Plan in chat. Wait for approval.

────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION GUIDANCE

- Models per PHARMACY §7. carts has user_id OR session_id (CHECK).

- Order numbers: format "PH-YYYY-NNNNNN" where N is per-year sequence.
  Use a small dedicated sequence table or MySQL's AUTO_INCREMENT
  with formatting on read. Suggestion: order_sequence(year, value)
  with row-locking increment. Document choice in DECISION_LOG.

- order_items snapshot: product_name_snapshot,
  product_sku_snapshot, batch_number_snapshot, expiry_date_snapshot.
  Population at insert time.

- delivery_address as JSONB(JSON in MySQL): full snapshot of the
  address at order time, even if user_address_id provided.

- Customer auth required for cart-write and checkout (anonymous can
  read /cart for guest carts via session cookie).

- Session cookie for guest carts: 'pharmacy_cart_session'; HttpOnly,
  SameSite=Lax. 30-day TTL.

- CheckoutService.quote:
     Returns totals (subtotal, delivery_fee, discount, total) +
     stock/price diffs (if any). Does NOT reserve stock.

- CheckoutService.place_order (THE transaction):
     1. Validate idempotency key.
     2. Open transaction.
     3. Re-load cart with items.
     4. For each item, allocate via InventoryService.allocate_for_
        order (Phase 6 method). Build allocation list.
     5. If any allocation insufficient → raise OutOfStockError with
        details.
     6. If any price changed from cart snapshot → raise
        PriceChangedError with details.
     7. Insert order with computed totals.
     8. Insert order_items (one per allocation; if a cart line
        spans 2 batches, generate 2 order_items? — design choice).
        Decision: ONE order_item per (order, product, batch) — so
        if 1 cart line spans 2 batches, that's 2 order_items.
        Snapshot all relevant fields. Sum to verify totals.
     9. Call InventoryService.reserve(allocations, order.id) →
        writes stock_movements 'reserved' and increments
        branch_products.reserved_quantity.
     10. Insert order_status_history (NULL → pending).
     11. If card payment: call payment integration (Phase 10
         FakePayment for now); store redirect_url.
     12. Commit.
     13. Enqueue 'send_sms' for order_placed (Phase 11; for now
         no-op queue from Phase 4).
     14. Store idempotency response.
     15. Return order summary.

- OrderService.cancel_by_customer:
     - Allowed if status ∈ {pending, confirmed}; else error
     - Open transaction
     - Update order.status = cancelled
     - InventoryService.release_reservations(order.id)
     - Insert status history
     - If payment_status=paid (card), enqueue refund task (Phase 10)
     - Enqueue order_cancelled SMS

────────────────────────────────────────────────────────────────────────────
TEST EXPECTATIONS — THIS IS THE PHASE WHERE TESTING MATTERS MOST

Concurrency:
  - test_two_orders_same_product_different_batches: succeeds, no
    overlap
  - test_two_orders_same_product_one_batch: only one succeeds, the
    other gets OutOfStockError
  - test_two_orders_split_across_batches: each gets a partial
    allocation
  - test_idempotent_double_submit: same key + body → same response
  - test_idempotent_conflict: same key + different body → 409

State machine:
  - test_pending_to_cancelled_releases_stock
  - test_cannot_cancel_when_preparing

Stock validation:
  - test_revalidate_stock_changed: cart line with reduced stock
    surfaces 409 with details
  - test_revalidate_price_changed: same

Snapshot integrity:
  - test_order_items_snapshot_matches_at_time_of_order:
    update product name later; old order still shows old name

Edge cases (representative):
  - test_max_per_order_enforced
  - test_cart_expired_cannot_checkout
  - test_guest_cart_merge_on_login
  - test_reorder_with_deleted_product_offers_alternatives

Run the FEFO concurrent test from Phase 6 again now that orders are
involved end-to-end.

────────────────────────────────────────────────────────────────────────────
OUT OF SCOPE

  - Real payment gateway (Phase 10 — use FakePayment placeholder)
  - SMS sending (Phase 11)
  - Admin order lifecycle (Phase 9)
  - Loyalty / coupons (Phase 2 product)

────────────────────────────────────────────────────────────────────────────
DEFINITION OF DONE

  [ ] All concurrency tests pass 50x in CI
  [ ] State transitions enforced at service layer
  [ ] Snapshots immutable and complete
  [ ] Idempotency works end-to-end
  [ ] Cart merge on login works
  [ ] Reorder flow works
  [ ] BACKEND §27 + PRODUCT §26 checklists pass
  [ ] Manual smoke test recipe in BUILD_PROGRESS:
      "register → search → add to cart → checkout COD → see order
       in /me/orders"

────────────────────────────────────────────────────────────────────────────
HAND-OFF

  Capture the smoke recipe in BUILD_PROGRESS. Confirm in chat that
  the system can place its first end-to-end order.
```


---

## Phase 9 — Admin Order Lifecycle, Reports & Audit

**Goal.** Admin order queue, picking screen API, status transitions with the right side effects, cancellations and refunds, sales/expiring/low-stock reports, audit log viewer.

**Input.** Phase 8 done. Customers can place orders.
**Output.** A pharmacist can pick orders; a branch manager can run reports; an audit trail is queryable.
**Estimated session length.** 2.5 hours.

### The prompt

```
You are a senior backend engineer building the admin order lifecycle and
operational tooling. Phases 1–8 are complete; orders are flowing.

────────────────────────────────────────────────────────────────────────────
SPECS TO RE-READ

Required:
  - PRODUCT_BLUEPRINT §7.5  (J-05 — order fulfillment journey)
  - PRODUCT_BLUEPRINT §7.6  (J-06 — near-expiry handling)
  - PRODUCT_BLUEPRINT §8.7  (Admin order features F-ADM-ORD-001..003)
  - PRODUCT_BLUEPRINT §8.9  (Reports F-RPT-001..002)
  - PRODUCT_BLUEPRINT §9    (Order state machine — verify enforcement)
  - PRODUCT_BLUEPRINT §17.2 (Order edge cases)
  - PRODUCT_BLUEPRINT §19   (Admin workflows + permissions matrix)
  - PHARMACY_BLUEPRINT §8   (Admin audit log schema)

────────────────────────────────────────────────────────────────────────────
MISSION

Models:
  - search_log (logs are written from Phase 7's search endpoint;
    the table arrives now if it didn't already in Phase 5/7;
    verify and add migration if missing)
  - admin_audit_log (added in Phase 5; verify it's complete)

Services:
  - OrderLifecycleService:
      - confirm(order_id, admin) — pending → confirmed
      - start_preparing(order_id, admin) — confirmed → preparing
      - swap_batch(order_id, item_id, new_batch_id, admin) — admin
        substitutes a different batch of same product during picking
      - mark_ready_for_pickup(order_id, admin) — preparing → ready;
        flips reservation to sold (calls Inventory service)
      - mark_out_for_delivery(order_id, courier_info, admin) —
        preparing → out_for_delivery; same flip
      - mark_delivered(order_id, admin) — → delivered
      - cancel_by_admin(order_id, reason, admin) — releases
        reservation (or restocks if dispatched-then-refused per
        §9.1 "out_for_delivery" → "cancelled" path)
      - refund(order_id, amount, reason, admin) — for paid orders;
        creates payment row of type refund (Phase 10 makes this
        real); for COD just status flip
  - ReportService:
      - sales_report(branch_id, from, to) — revenue, units, AOV,
        top products, top categories
      - top_products(branch_id, from, to, limit)
      - export_csv (StreamingResponse for any report)
  - AuditService:
      - log(actor, action, entity_type, entity_id, before, after,
        ip, user_agent) — used as a helper called from every admin
        mutation (already wired in Phase 5/6; verify completeness
        and add wherever it's missing)
      - search(filters, page) — for the viewer

Admin API:
  - GET  /admin/orders                  (list with filters)
  - GET  /admin/orders/:id
  - POST /admin/orders/:id/confirm
  - POST /admin/orders/:id/start-preparing
  - POST /admin/orders/:id/items/:item_id/swap-batch
  - POST /admin/orders/:id/mark-ready
  - POST /admin/orders/:id/dispatch     {courier_name, courier_phone}
  - POST /admin/orders/:id/mark-delivered
  - POST /admin/orders/:id/cancel       {reason}
  - POST /admin/orders/:id/refund       {amount, reason}
  - GET  /admin/orders/:id/picking-sheet (printable PDF — optional;
    minimum: HTML view that prints well)
  - GET  /admin/reports/sales?from=&to=&branch=&format=
  - GET  /admin/reports/top-products?from=&to=&branch=&limit=
  - GET  /admin/audit?actor=&entity=&from=&to=&page=

────────────────────────────────────────────────────────────────────────────
PLAN FIRST — DEEP THINKING

1. THE STATE TRANSITION TABLE (PRODUCT §9.1):
   Build a transitions config dict in code that maps (from, to)
   to: who can trigger, what side-effects, what events to emit.
   Use this as a single source of truth in
   OrderLifecycleService. Don't hand-code the rules in 10 places.

2. STOCK SIDE-EFFECT TIMING:
   - reserve at place_order (Phase 8 already did this)
   - convert reserved → sold at preparing → ready/dispatch
   - release at any cancel BEFORE preparing→ready/dispatch
   - restock at out_for_delivery → cancelled (refused at door)
   - never restock from delivered → refunded (PRODUCT §9.1)
   Verify InventoryService has the methods needed; add missing.

3. BATCH SWAP DURING PICKING:
   Pharmacist found a different batch of the same product.
   - Validate same product
   - Validate batch belongs to branch
   - Validate batch has enough quantity_remaining
   - Update order_item.inventory_batch_id and snapshots
   - Update stock_movements: release on the old batch, reserve
     on the new batch (still 'reserved' state; conversion to
     sold happens later)

4. REFUND HANDLING:
   For COD: status flip only; cash never moved.
   For card: needs gateway refund (Phase 10). For Phase 9,
   create a refund row marked 'pending' in payments table; admin
   completes manually.
   Document carefully in DECISION_LOG.

5. AUDIT LOG SCOPE:
   Every admin write goes through admin_audit_log. Provide a
   decorator @audited(entity_type) for service methods, OR use
   a context-manager. Either way, before/after diffs are
   automatic. Keep it DRY.

6. REPORT QUERIES:
   Sales report aggregates over orders + order_items. For thousands
   of orders / month this is fine on the OLTP DB. Add an index hint
   if a query plan looks bad.

Sub-agents:
  Agent A: Audit every admin endpoint built in Phases 5 and 6 to
           confirm admin_audit_log is being written. List any
           gaps. Fix them in this phase if any.
  Agent B: Sketch the state transition config dict in code form,
           covering every transition from PRODUCT §9.1.

TodoWrite plan with 14–18 items. Plan in chat. Wait for approval.

────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION GUIDANCE

- State transition config:

  ALLOWED_TRANSITIONS = {
      ('pending', 'confirmed'): TransitionRule(
          allowed_roles=(SUPER_ADMIN, BRANCH_MANAGER, PHARMACIST),
          on_success=[],
      ),
      ('pending', 'cancelled'): TransitionRule(
          allowed_roles=(SUPER_ADMIN, BRANCH_MANAGER, PHARMACIST),
          on_success=[release_reservations, sms_cancelled],
          requires_reason=True,
      ),
      ...
  }

- Each transition method calls a single dispatch() that checks rules
  and runs side-effects in a transaction.

- Cancellation reasons: predefined enum + free-text "other" with
  required notes. Reasons:
     customer_changed_mind, out_of_stock_at_picking, customer_unreachable,
     customer_refused_at_door, payment_failed, auto_timeout_unconfirmed,
     other

- Picking sheet HTML: render a server-side template (Jinja2). Minimal
  styling, monospaced, print-friendly. Title, customer, items with
  batch and shelf placeholder, totals.

- Reports: cache 5 min for repeated identical queries. CSV export
  via StreamingResponse with proper utf-8 BOM for Excel.

- Audit viewer:
     - Filters: actor, entity_type, entity_id, action, date range
     - Paginated cursor-based
     - Detail view shows JSON diff (before vs after) prettified

────────────────────────────────────────────────────────────────────────────
TEST EXPECTATIONS

State machine:
  - test_state_transitions_matrix: every disallowed transition
    raises; every allowed succeeds
  - test_cancel_pending_releases_stock
  - test_cancel_dispatched_restocks_to_original_batch
  - test_cannot_cancel_delivered

Side-effects:
  - test_mark_ready_converts_reserved_to_sold
  - test_swap_batch_during_picking
  - test_refund_creates_pending_payment_row

Reports:
  - test_sales_report_aggregations (with seeded orders)
  - test_top_products_ordering
  - test_csv_export_streams

Audit:
  - test_every_admin_mutation_writes_audit
  - test_audit_diff_view

────────────────────────────────────────────────────────────────────────────
OUT OF SCOPE

  - Actual gateway refund (Phase 10)
  - Real-time push to admin (WebSocket / SSE — not in plan)
  - Inventory valuation report (Phase 1.5)
  - Customer cohort report (Phase 2 product)

────────────────────────────────────────────────────────────────────────────
DEFINITION OF DONE

  [ ] All state transitions enforced via config + dispatch
  [ ] Stock side-effects correct on all paths
  [ ] Audit log writes confirmed across all admin endpoints
  [ ] Reports return correct numbers (verified vs hand-computed
      from seeded fixtures)
  [ ] All tests pass
  [ ] BACKEND §27 + PRODUCT §26 checklists pass

────────────────────────────────────────────────────────────────────────────
HAND-OFF

  Demonstrate the admin lifecycle: place an order as customer,
  switch to admin user, confirm → prepare → dispatch → deliver.
  Capture in BUILD_PROGRESS. Pull a 30-day sales report after
  seeding test orders.
```

---

## Phase 10 — Integrations: SMS, Payments, Storage

**Goal.** Replace fakes from previous phases with real adapters: SMS via Nikita (or chosen provider), Payment via Freedom Pay (COD already works; this enables card), Storage via Cloudflare R2. Each behind a Protocol with a fake implementation for tests.

**Input.** Phase 9 done.
**Output.** SMS actually goes out. Card payments work end-to-end. Images stored on R2.
**Estimated session length.** 3 hours (heavy on third-party docs).

### The prompt

```
You are a senior backend engineer integrating external services for the
Pharmacy Platform. The system works end-to-end with fakes; this phase
replaces the fakes.

────────────────────────────────────────────────────────────────────────────
SPECS TO RE-READ

Required:
  - PRODUCT_BLUEPRINT §11.5 (Payment UX flow)
  - PRODUCT_BLUEPRINT §14   (Notification strategy)
  - PRODUCT_BLUEPRINT §17.6, §17.7 (Payment & delivery edge cases)
  - PRODUCT_BLUEPRINT §21.3 (SMS templates)
  - PHARMACY_BLUEPRINT §7.6, §7.7 (Payments + deliveries schema)
  - BACKEND_BLUEPRINT §3 / integrations folder structure
  - BACKEND_BLUEPRINT §17.3 (Job pattern)
  - BACKEND_BLUEPRINT §19   (Image pipeline detail)

Web research as needed:
  - Nikita SMS API docs (or chosen provider)
  - Freedom Pay merchant API docs
  - Cloudflare R2 + boto3 quickstart
  - Cyrillic SMS encoding (UCS-2 vs GSM-7) for length calculation

────────────────────────────────────────────────────────────────────────────
MISSION

Add models if not yet present:
  - payments (added in Phase 8 schema-wise; if not migrated yet,
    add now)
  - deliveries

Integration adapters in app/integrations/:

  sms/
    base.py          # SmsClient Protocol: send(phone, body) -> SendResult
    nikita.py        # real implementation
    fake.py          # test fake; logs calls, configurable success
    factory.py       # returns instance based on settings.sms_provider

  payments/
    base.py          # PaymentClient Protocol:
                     #   create_intent(order, amount) -> {redirect_url, txn_id}
                     #   refund(payment_id, amount) -> {refund_id}
                     #   verify_webhook(payload, signature) -> ParsedEvent
    freedom_pay.py
    fake.py
    factory.py

  storage/
    base.py          # StorageClient Protocol:
                     #   upload(key, file, content_type) -> public_url
                     #   delete(key)
                     #   sign_url(key, ttl) -> presigned_url
    r2.py
    fake.py          # writes to local /tmp/r2 in dev/test
    factory.py

Webhook routes (admin domain or system domain):
  - POST /webhooks/payments/freedom-pay (signature-verified)
    → parses event → updates payments.status → moves order.status

ARQ jobs that use these (worker registration is Phase 11; the
function bodies come now):
  - send_sms (uses sms client)
  - process_image_upload (uses storage client)
  - reconcile_payments (uses payment client to verify pending
    payments older than X minutes)

────────────────────────────────────────────────────────────────────────────
PLAN FIRST

1. Confirm chosen providers. The blueprints recommend Nikita and
   Freedom Pay. If the team hasn't chosen, add to OPEN_QUESTIONS
   and surface. For Phase 10, assume these unless told otherwise.

2. Look up current API contracts. Nikita and Freedom Pay have
   evolved; web search and read their current docs. Don't trust
   training data.

3. SMS specifics:
     - Cyrillic body uses UCS-2 → 70 chars per segment.
     - Verify our templates fit; flag any that exceed.
     - Handle delivery receipts if provider supports them — at
       MVP, fire-and-forget then poll status periodically (or just
       trust the provider's response).
     - Phone format: providers vary on accepted formats. Normalise
       to digits-only or +E.164 per provider docs.

4. Payment specifics:
     - Freedom Pay typically requires:
         - merchant_id, secret_key, request signature
         - return URL and webhook URL
     - Test/sandbox env: use sandbox creds in settings; production
       uses real
     - Webhook signature verification is mandatory — never trust
       unsigned events
     - Amount unit: kopecks (×100) usually — confirm
     - Currency: KGS

5. R2 specifics:
     - boto3 with custom endpoint_url
     - Public bucket vs presigned URLs: catalog images are public
       (CDN-served via cdn.pharmacy.kg); admin exports are private
       with presigned URLs
     - Image variants per BACKEND §19 — 200, 600, 1200 WebP

6. Test strategy:
     - Unit tests of adapters use the fakes
     - One integration test per real adapter, gated by env vars
       (skips if creds absent)
     - Webhook verification has its own test with known fixtures

Sub-agents:
  Agent A: Research current Nikita SMS API; produce a
           one-page spec of: auth, endpoint, request/response
           shape, error codes, rate limits.
  Agent B: Research current Freedom Pay API; produce same.
  Agent C: Research R2 boto3 quirks (signing, region naming).

TodoWrite plan with 16–22 items. Plan in chat. Wait for approval.

────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION GUIDANCE

- Each adapter exposes async methods (use httpx for HTTP).

- Use tenacity for retries with jittered backoff on transient
  errors. Never retry on 4xx (auth, validation). Retry on 5xx and
  network errors up to 3 times.

- Fakes:
     - SmsFake records calls in a list; tests assert calls.
     - PaymentFake returns synthetic redirect URL + txn_id.
       create_intent succeeds; refund succeeds; verify_webhook
       trusts whatever it's given (test config).
     - StorageFake writes to local dir; returns file:// URL.

- Factory pattern in factory.py reads settings.<provider> and
  returns the configured instance. Inject into services via deps.

- Webhook handler:
     - No auth (it's signed)
     - Verify signature — reject 400 if invalid
     - Parse event
     - Call PaymentReconcileService.handle_webhook(event)
     - Idempotent: same event_id processed twice is a no-op

- SMS template rendering: use the i18n machinery to look up the
  template, interpolate variables. Phone of recipient and language
  per PRODUCT §14.2.

- Delivery records: created when an order moves to
  out_for_delivery. Stores courier_name, courier_phone,
  tracking_number (if any), provider (in_house default).

────────────────────────────────────────────────────────────────────────────
TEST EXPECTATIONS

Unit (with fakes):
  - test_sms_factory_returns_correct_provider
  - test_sms_send_records_call
  - test_payment_create_intent
  - test_payment_refund
  - test_storage_upload_returns_url

Webhook:
  - test_webhook_invalid_signature_rejected
  - test_webhook_valid_event_updates_payment
  - test_webhook_idempotent_replay

Service flow:
  - test_place_order_card_calls_payment (using fake) returns
    redirect_url
  - test_payment_paid_webhook_promotes_order_to_confirmable
  - test_refund_calls_gateway

Integration (gated):
  - test_real_sms_sandbox_send (skips if no creds)
  - test_real_freedom_pay_sandbox_intent (skips if no creds)
  - test_real_r2_upload (skips if no creds)

────────────────────────────────────────────────────────────────────────────
OUT OF SCOPE

  - SMS opt-out management (Phase 2)
  - Multi-provider failover (Phase 2)
  - Payment provider #2 (Phase 2)
  - Refrigerated delivery via courier API (Phase 2)

────────────────────────────────────────────────────────────────────────────
DEFINITION OF DONE

  [ ] SMS: production setting wired; sandbox tested
  [ ] Payments: card flow runs end-to-end with real sandbox
  [ ] R2: image upload works in dev with R2 sandbox creds
  [ ] All fakes satisfy the protocol; tests use them by default
  [ ] Webhook signature verification proven
  [ ] Sentry breadcrumbs emitted on integration failures
  [ ] BACKEND §27 + PRODUCT §26 checklists pass

────────────────────────────────────────────────────────────────────────────
HAND-OFF

Demonstrate: place an order with card; complete the sandbox
payment; webhook updates order; pharmacist marks delivered. Receive
SMS at every step in the SmsFake call log.
```

---

## Phase 11 — Background Jobs (ARQ) & Scheduled Tasks

**Goal.** ARQ worker fully wired with all jobs from BACKEND §18 and PRODUCT requirements: send_sms, process_image_upload, process_product_import (replacing inline import for >500 rows), generate_admin_report, and all cron-like scheduled jobs.

**Input.** Phase 10 done.
**Output.** Worker container runs all jobs. Scheduled tasks fire on time.
**Estimated session length.** 2 hours.

### The prompt

```
You are a senior backend engineer wiring background jobs for the Pharmacy
Platform. Phases 1–10 are complete; integrations work. Many things have
been "no-op enqueued" so far — this phase makes them real.

────────────────────────────────────────────────────────────────────────────
SPECS TO RE-READ

Required:
  - BACKEND_BLUEPRINT §17 (Background Jobs ARQ — all)
  - BACKEND_BLUEPRINT §19 (Image pipeline)
  - PHARMACY_BLUEPRINT §18 (Background jobs catalogue)
  - PRODUCT_BLUEPRINT §10.6 (Reservation timeout — release jobs)
  - PRODUCT_BLUEPRINT §14   (SMS triggers)
  - PRODUCT_BLUEPRINT §F-ADM-INV-003 (near-expiry/low-stock daily email)

────────────────────────────────────────────────────────────────────────────
MISSION

Configure ARQ (app/workers/settings.py) per BACKEND §17.2.

Implement these on-demand jobs (in app/workers/):
  - send_sms(phone, body, purpose) — uses Phase 10 SMS client; logs
    to sms_log
  - send_email(to, subject, body, purpose) — basic SMTP via aiosmtp
    or use a transactional email service (skip if blocked; document)
  - process_image_upload(temp_path, product_id) — uses Pillow +
    storage client; persists product_images rows
  - process_product_import(import_id) — uses CatalogService;
    streams progress
  - generate_admin_report(report_id) — runs ReportService;
    uploads CSV to R2; emails link

Implement these scheduled jobs (with cron schedules from BACKEND §17.2):
  - near_expiry_report — 06:00 Asia/Bishkek daily
  - low_stock_report — 06:10 daily
  - expire_batches — 02:00 daily (mark batches with expiry_date <
    today as fully expired in stock_movements; recompute total_qty)
  - reconcile_stock_cache — 03:00 daily
  - cleanup_otps — 04:00 daily (delete consumed/expired older than
    7 days)
  - cleanup_carts — 04:10 daily (delete carts past expires_at)
  - release_pending_orders — every hour (cancel orders pending > 24h
    or card-pending > 30 min)
  - payment_reconcile — every hour (verify pending card payments
    against gateway)
  - cleanup_idempotency_keys — daily (Redis SCAN + delete expired —
    Redis handles this natively, but verify)

Worker entrypoint and Docker:
  - app/worker.py main entrypoint
  - docker-compose worker service (already in Phase 1's compose
    or add now)
  - Production Dockerfile target for worker (multistage; same image,
    different CMD)

────────────────────────────────────────────────────────────────────────────
PLAN FIRST

1. Idempotency of scheduled jobs:
     - near_expiry_report: composes the same email each run; OK to
       re-run
     - expire_batches: should only mark items not already expired;
       use status checks in the query
     - release_pending_orders: lock the order rows FOR UPDATE
       SKIP LOCKED before checking and cancelling; multiple workers
       safe
     - payment_reconcile: idempotent webhook handler covers the
       case of double processing

2. Long-running jobs:
     - process_product_import on a 5,000-row file may take minutes.
       Stream progress to a Redis hash so the admin UI can poll.
     - Job timeout: ARQ default 5 min; for imports, set higher
       per-job (job_timeout overridable per function).

3. Queue separation (optional):
     - One queue is fine for MVP. Document. Phase 2 can split
       into "fast" (sms, sub-second) and "slow" (imports, reports).

4. Worker concurrency:
     - max_jobs=10 per worker per BACKEND §17.2 default. Tunable
       via env.

5. Test approach:
     - Use ARQ's testing utilities to drive jobs without real
       Redis polling
     - Mock the SMS/payment/storage clients in worker tests

Sub-agents:
  Agent A: Validate the cron expressions match Asia/Bishkek
           timezone behaviour (ARQ uses UTC by default; document
           how Bishkek time is achieved).
  Agent B: Audit every place in Phases 4–10 where a no-op queue
           was used; produce a list of integration points where
           jobs are now actually called.

TodoWrite plan with 14–18 items. Plan in chat. Wait for approval.

────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION GUIDANCE

- Worker startup hooks: configure logging, sentry, redis pool.

- Each job function follows the pattern in BACKEND §17.3:
     async def send_sms(ctx, *, phone, body, purpose):
         async with session_scope() as session:
             ...

- For Bishkek-time crons: ARQ's cron uses UTC. Subtract 6 (KG is
  UTC+6, no DST). 06:00 KG = 00:00 UTC. Document this in code
  comments to avoid future-you confusion.

- generate_admin_report writes to R2 under exports/<report_id>/...
  and emails the admin a presigned URL valid for 24h.

- expire_batches scope: marks batches with expiry_date < today as
  expired by writing stock_movements 'expired' for the remaining
  quantity, sets quantity_remaining=0. Then triggers
  reconcile_branch_product for each affected (branch,product).

- release_pending_orders: query for status='pending' AND
  placed_at < now - 24h. For each: open transaction, cancel,
  release reservations, write status history with reason
  'auto_timeout_unconfirmed'. Send SMS.

- payment_reconcile:
     - Look up pending card payments older than 5 min
     - Call payment client verify(txn_id) — most gateways have a
       lookup endpoint
     - Update status accordingly; if paid, mark order confirmable

- All jobs emit a structured log with job_name, job_id, duration.

────────────────────────────────────────────────────────────────────────────
TEST EXPECTATIONS

Unit (with mocked clients and DB):
  - test_send_sms_writes_log_and_calls_client
  - test_process_image_upload_creates_variants
  - test_expire_batches_marks_only_expired
  - test_release_pending_orders_only_after_24h
  - test_reconcile_stock_cache_corrects_drift

Integration (real Redis, real DB):
  - test_arq_enqueue_and_run: enqueue send_sms, run worker briefly,
    assert log row created
  - test_scheduled_near_expiry_runs

Idempotency:
  - test_release_pending_orders_concurrent_workers_safe
  - test_reconcile_payment_webhook_then_job_no_double_handle

────────────────────────────────────────────────────────────────────────────
OUT OF SCOPE

  - Multi-queue routing (Phase 2)
  - Job priority lanes (Phase 2)
  - Distributed worker scaling concerns (handle in deploy phase)

────────────────────────────────────────────────────────────────────────────
DEFINITION OF DONE

  [ ] Worker container builds and runs
  [ ] All on-demand jobs fire from API actions
  [ ] All scheduled jobs registered with correct cron
  [ ] Image worker replaces inline resize from Phase 5
  [ ] Bulk import worker handles >500 rows
  [ ] All cron jobs verified to run in dev (force-run for test)
  [ ] BACKEND §27 + PRODUCT §26 checklists pass

────────────────────────────────────────────────────────────────────────────
HAND-OFF

Force-run each scheduled job manually (CLI helper) and verify
expected output. Capture in BUILD_PROGRESS.
```

---

## Phase 12 — Hardening & Launch Readiness

**Goal.** The pre-launch sweep. Comprehensive E2E test pass, observability (Sentry, structured-log review), performance pass (EXPLAIN on hot queries, index audit), security pass, documentation, deployment configuration, runbooks. Everything that turns a built system into a launchable system.

**Input.** Phase 11 done. The system functionally works.
**Output.** Production-ready deployment artifact. Runbooks. Launch checklist green.
**Estimated session length.** 3–4 hours, possibly two sessions.

### The prompt

```
You are a senior backend engineer doing the pre-launch hardening pass.
The system works end-to-end. This phase is about robustness, observability,
and deployability — the difference between "code is done" and "system is
ready."

────────────────────────────────────────────────────────────────────────────
SPECS TO RE-READ

Required:
  - BACKEND_BLUEPRINT §20 (Security)
  - BACKEND_BLUEPRINT §21 (Observability)
  - BACKEND_BLUEPRINT §22 (Deployment topology)
  - BACKEND_BLUEPRINT §23 (Scaling roadmap — for context)
  - BACKEND_BLUEPRINT §24 (Backups & DR)
  - BACKEND_BLUEPRINT §25 (Open questions — verify all resolved)
  - PRODUCT_BLUEPRINT §15 (Trust signals — must be visible in API responses)
  - PRODUCT_BLUEPRINT §20 (Compliance, ethics & safety)
  - PRODUCT_BLUEPRINT §22 (Success metrics & analytics events)
  - PRODUCT_BLUEPRINT §24 (Risk register)

────────────────────────────────────────────────────────────────────────────
MISSION

This phase has many independent workstreams. Use sub-agents
aggressively.

Stream 1 — End-to-End Test Pass:
  - Write a comprehensive E2E test suite that walks every
    customer journey (PRODUCT §7) and every admin workflow
    (PRODUCT §19)
  - Add load-test script (k6 or locust) for catalog browse +
    place-order; baseline numbers captured

Stream 2 — Observability:
  - Sentry: confirm DSN-driven init; PII scrubbing; release
    tagging
  - Structured logs: review every log line emitted; redact PII;
    consistent field naming
  - Metrics: add prometheus client; expose /metrics endpoint
    (admin-only or behind LB-only)
  - Add health checks: /health (liveness — does the app respond),
    /health/ready (readiness — DB and Redis reachable)
  - Analytics events emit per PRODUCT §22.7 to a structured log
    channel "events"

Stream 3 — Performance:
  - EXPLAIN every query in critical paths (catalog list, search,
    place-order, admin order list); confirm index hits
  - Add query timing log for queries > 100ms
  - Verify cache hit rates in dev with realistic load
  - N+1 audit: spawn a sub-agent to grep for any lazy="raise"
    bypasses; fix

Stream 4 — Security:
  - Run BACKEND §20.6 OWASP checklist
  - Verify: rate limits in place; CORS narrow; CSP headers;
    HTTPS-only cookies; HSTS; audit log on every admin mutation
  - Secrets: nothing checked in; .env.example complete; vault/
    env-var rotation procedure documented
  - Run pip-audit / trivy on the image; address criticals

Stream 5 — Deployment:
  - Production Dockerfile cleaned up (multistage, non-root user,
    healthcheck)
  - docker-compose.production.yml or k8s manifests (per chosen
    target — VPS docker compose for MVP per PHARMACY §22.2)
  - Secrets management documented
  - Deployment runbook in docs/runbooks/deploy.md
  - Rollback runbook in docs/runbooks/rollback.md
  - DB backup runbook in docs/runbooks/backups.md
  - Common-incident runbooks: stuck job, payment webhook missed,
    disk full

Stream 6 — Documentation:
  - README updated with everything a new developer needs
  - OpenAPI spec reviewed; tags, summaries, descriptions on every
    endpoint
  - ARCHITECTURE.md (1-page overview) — mirrors PHARMACY §14
    diagram in repo
  - CONTRIBUTING.md (how to make changes, branch + PR conventions)
  - Per BACKEND §27 / PRODUCT §26: confirm both checklists pass
    for the entire codebase, not just the latest phase

Stream 7 — Pre-launch verification:
  - Smoke test against staging (or local docker-compose if no
    staging yet)
  - Manual run-through of every PRODUCT §7 journey
  - Admin walkthrough by Aida-persona perspective: receive,
    pick, dispatch
  - Backup → restore drill
  - Deliberate failure tests: kill DB mid-flight, kill Redis,
    kill payment webhook; verify graceful behaviour

────────────────────────────────────────────────────────────────────────────
PLAN FIRST — STRUCTURE THE SWEEP

This phase is unusual: many threads, fewer brand-new features. Plan
carefully so nothing slips through.

1. Use deep thinking to identify likely-weak spots based on what's
   been built. For each, pre-design the test or fix.

2. SUB-AGENT STRATEGY:
   - Launch up to 4 parallel agents, each owning a stream:
     Agent A — Stream 1 (E2E test pass): builds a comprehensive
               test inventory and writes the missing tests.
     Agent B — Stream 3 (Performance): runs EXPLAIN on every
               candidate hot path; produces an index audit;
               proposes fixes.
     Agent C — Stream 4 (Security): runs through the OWASP
               checklist; produces a punchlist of fixes.
     Agent D — Stream 6 (Documentation): produces the README,
               ARCHITECTURE, runbooks based on the existing
               state of the code.

   While agents work in parallel, you handle:
     Stream 2 (observability code changes that touch many
               files)
     Stream 5 (deployment artifacts)
     Stream 7 (manual verification — only you can run end-to-
               end smoke tests reliably)

3. Synthesise outputs from agents. Apply fixes one stream at a
   time.

4. TodoWrite plan with 25–35 items. Plan in chat. Wait for
   approval.

────────────────────────────────────────────────────────────────────────────
IMPLEMENTATION GUIDANCE

- Sentry: app/main.py + app/worker.py both call sentry_sdk.init
  with the same DSN. Set traces_sample_rate=0.1, profiles_sample
  _rate=0.1. Tag with environment and release (git SHA from CI).

- /metrics endpoint: prometheus_client; expose Counter for HTTP
  requests by route+status, Histogram for latency, Counter for
  job runs by job+status. Behind a simple Bearer-token guard or
  IP allowlist (LB-only).

- Health checks:
     /health: returns {"status":"ok","version":...} unconditionally
     /health/ready: pings DB (SELECT 1) and Redis (PING); 503 on
       either failure
   Readiness is what the LB uses for traffic routing.

- Gunicorn config:
     worker_class = uvicorn.workers.UvicornWorker
     workers = 2 * cpus + 1 (start with 4)
     timeout = 60
     graceful_timeout = 30
     max_requests = 5000 + jitter (recycle workers)

- Backup script:
     bin/backup_db.sh: mysqldump | gzip | aws s3 cp to R2
     Cron via the host (not ARQ) for redundancy
     Encrypted via openssl with key in vault

- Restore drill:
     bin/restore_db.sh: gunzip | mysql
     Run monthly in staging to prove backups are restorable
     Document expected time

────────────────────────────────────────────────────────────────────────────
TEST EXPECTATIONS

By the end of this phase:
  - Backend test coverage ≥ 85% on app/domain and app/api
  - Every PRODUCT §7 journey has at least one E2E test
  - Every state transition in PRODUCT §9 has a test
  - Every PRODUCT §17 edge case has a test or a documented "TODO
    Phase X" comment
  - Load test baseline numbers captured (e.g., 50 RPS catalog
    browse with p95 < 200ms)

────────────────────────────────────────────────────────────────────────────
OUT OF SCOPE

  - Anything Phase 1.5 / Phase 2 from PRODUCT §23
  - Frontend (this is a backend project at this stage)
  - Real production deployment (separate effort with ops team)

────────────────────────────────────────────────────────────────────────────
DEFINITION OF DONE — THE LAUNCH CHECKLIST

Code & Tests:
  [ ] All PRODUCT §7 journeys covered by E2E tests
  [ ] All state transitions tested
  [ ] Coverage ≥ 85% on app/domain and app/api
  [ ] No TODO / FIXME without an issue link
  [ ] No skipped tests except those gated on real-creds env vars
  [ ] BACKEND §27 + PRODUCT §26 checklists pass for the WHOLE codebase

Security:
  [ ] OWASP §20.6 punchlist green
  [ ] No secrets in repo (verified by truffleHog or similar scan)
  [ ] Dependencies clean (pip-audit / trivy)
  [ ] HTTPS-only cookies; HSTS; CSP; secure headers verified
  [ ] All admin mutations audited

Observability:
  [ ] Sentry capturing errors with PII scrubbed
  [ ] Structured logs with consistent fields
  [ ] /metrics serving prometheus format
  [ ] /health and /health/ready behave correctly
  [ ] Analytics events emitting per PRODUCT §22.7

Performance:
  [ ] Hot-path queries verified by EXPLAIN
  [ ] No N+1 in critical paths
  [ ] Cache invalidation verified
  [ ] Load test baseline captured

Deployment:
  [ ] Production Dockerfile builds, runs as non-root, has healthcheck
  [ ] docker-compose.production.yml runs the full stack
  [ ] Backup script runs and restores tested
  [ ] Runbooks: deploy, rollback, backups, common incidents

Documentation:
  [ ] README gets new dev to running app in ≤ 5 min
  [ ] ARCHITECTURE.md reflects current truth
  [ ] CONTRIBUTING.md explains branch/PR/commit conventions
  [ ] OpenAPI docs reviewed; every endpoint has summary + tags
  [ ] All runbooks tested by following them step by step

OPEN_QUESTIONS:
  [ ] All resolved or explicitly punted to Phase 1.5+ with rationale

────────────────────────────────────────────────────────────────────────────
HAND-OFF

  1. Update BUILD_PROGRESS.md: Phase 12 → done. Project at MVP-
     ready state.
  2. CHANGELOG.md: 1.0.0-rc1 entry summarising the release.
  3. Tag the commit `v1.0.0-rc1`.
  4. Create LAUNCH_CHECKLIST.md mirroring the DoD above with each
     item ticked + linked to the verification artifact (test
     name, runbook page, etc.).
  5. Post chat summary: launch readiness state, recommended next
     steps (deploy to staging, beta, GA).
  6. STOP.
```


---

# Part 4 — Meta-Prompts

> Use these whenever they apply, irrespective of which phase you're in. They are tools, not phases.

## Code Review Prompt

Use this **before merging any phase's PR** — even when working solo, the act of running this prompt produces a meaningful pre-merge audit.

```
You are a senior staff engineer doing a code review on the Pharmacy
Platform. Be exacting but constructive. Optimise for code that will
still make sense in two years.

Context:
  - Read the PR description / commit log carefully
  - Read BUILD_PROGRESS.md to understand which phase this is
  - Read the relevant phase's prompt in CLAUDE_CODE_PROMPTS.md to
    understand what was supposed to ship

Your review must walk these layers in order:

1. SPEC ALIGNMENT
   - Does this implementation match the relevant blueprint sections?
     Cite the section numbers it should match.
   - Are there silent deviations? If yes, are they in DECISION_LOG.md
     with rationale?
   - Is anything from the phase's "out of scope" list creeping in?

2. DOMAIN CORRECTNESS
   - For inventory changes: FEFO honoured, expiry blocks enforced,
     reservation lifecycle correct?
   - For order changes: state machine matches PRODUCT §9.1?
   - For catalog changes: i18n, slug, image, FULLTEXT — all per spec?
   - For auth: rate limits, token rotation, session revocation —
     correct?

3. CONCURRENCY AND CORRECTNESS
   - Any shared mutable state without locks?
   - Any missing FOR UPDATE / SKIP LOCKED in transactional reads
     that should have them?
   - Any race conditions? Walk through scenarios.
   - Any commit-in-loop? Any commit-then-fail-after that leaks
     state?

4. ERROR HANDLING
   - Every external call wrapped (httpx, redis, db)?
   - Errors raise specific exceptions, not bare Exception?
   - User-facing errors carry a code, not a stack trace?
   - Logging on the failure path includes enough context for
     debugging (request_id, entity_id)?

5. SECURITY
   - Any user input flowing into queries without parameter binding?
   - Any auth check missing on a sensitive endpoint?
   - Any PII leaking into logs?
   - Any untrusted input deserialized without bounds (e.g. JSON
     blobs that should be size-limited)?
   - Secrets ever in code or in commit messages?

6. PERFORMANCE
   - Any N+1 you can see? (Look for ORM access in loops.)
   - Any missing index on a column in a WHERE/JOIN/ORDER BY?
   - Any cache that should exist? Any cache without invalidation?

7. TESTING
   - Are the tests testing behaviour or testing implementation?
   - Are concurrency-sensitive paths concurrency-tested?
   - Is there at least one E2E test for the new feature?
   - Are tests deterministic? (No reliance on system clock or
     random ordering.)

8. READABILITY
   - Function/class names communicate intent?
   - Comments explain WHY, not WHAT?
   - Any dead code, unused imports, debug prints?
   - Type hints accurate? mypy strict still clean?

9. CONVENTIONS
   - BACKEND §27 checklist points relevant to this PR — pass?
   - PRODUCT §26 checklist points relevant to this PR — pass?
   - Conventional Commits format on the merge commit?

OUTPUT FORMAT:

Produce a review with three sections:

  BLOCKERS (must fix before merge)
    - [path/file.py:line] Issue + suggested fix

  SUGGESTIONS (consider before merge)
    - [path/file.py:line] Issue + suggested approach

  PRAISE (what was done well, briefly)
    - …

End with a one-line verdict: APPROVE / REQUEST CHANGES / NEEDS DISCUSSION.

If you find a BLOCKER, do not also fix it. Surface it; let the
implementing engineer (or next prompt) fix.
```

## Debugging Prompt

Use this when something breaks and you need to dig methodically rather than guess.

```
You are a senior engineer debugging an issue in the Pharmacy Platform.
Resist the urge to guess and patch. Diagnose first.

Issue (one paragraph from the user):
  [paste the failure description, log lines, and reproduction]

Your protocol:

1. REPRODUCE
   - Reproduce locally if possible. If not reproducible, gather
     enough information to understand the failure path.
   - Capture the exact error, stack, and request_id.

2. CONTEXT
   - Which phase introduced the affected code? Read its prompt.
   - Which spec sections govern this behaviour? Read them.
   - Which recent commits touched the path?

3. HYPOTHESES
   - List 3–5 possible causes, ordered by likelihood.
   - For each, identify the cheapest test to prove or disprove it.

4. DEEP THINKING
   - Pick the most likely. Walk through the data flow end-to-end.
     What does each layer assume? Where might assumptions break?
   - For concurrency bugs: draw the interleaving on paper. For
     state bugs: dump the row before and after. For logic bugs:
     trace inputs through the function with a notebook.

5. SUB-AGENTS (if useful)
   - One agent reads recent commits diff for the affected files.
   - Another reads the spec sections and produces a check matrix.
   - You synthesise.

6. FIX
   - Smallest change that addresses the root cause, not the
     symptom.
   - Add a regression test that fails without the fix and passes
     with it.
   - If the fix exposes a deeper issue, surface it. Don't paper
     over.

7. VERIFY
   - Run the new test.
   - Run the broader test suite.
   - If state was corrupted, write a one-off migration or script
     to repair (commit it under bin/repair_NNNN.py with a
     description).

8. DOCUMENT
   - Update DECISION_LOG.md if the fix changes a non-obvious
     behaviour.
   - Update RISKS.md if this surfaced a class of bug we should
     watch for.
   - Add to CHANGELOG.md under Fixed.

OUTPUT:

  Diagnosis: <one paragraph>
  Root cause: <pinpointed code/data>
  Fix: <pasteable diff>
  Regression test: <pasteable code>
  Notes for the team: <if anything notable>
```

## Spec Ambiguity Resolution Prompt

Use this when the three blueprints disagree, are silent on a case, or you're uncertain whether to deviate.

```
You are a senior engineer resolving a spec ambiguity on the Pharmacy
Platform. Don't decide alone if the decision has product implications.

Ambiguity:
  [describe the case briefly]

Process:

1. SURFACE THE EXACT POINTS
   - What does PRODUCT_BLUEPRINT say? Quote section + lines.
   - What does PHARMACY_BLUEPRINT say? Quote.
   - What does BACKEND_BLUEPRINT say? Quote.
   - What was the implicit assumption you were going to make?

2. CLASSIFY
   - Is this a product behaviour question? (User-visible. Needs PM.)
   - Is this a data/structure question? (Schema or persistence.
     Needs eng/architect.)
   - Is this an implementation choice? (No external impact.
     Decide and log.)

3. PRECEDENCE RULE
   When the three docs disagree:
     - PRODUCT_BLUEPRINT wins on user-visible behaviour
     - BACKEND_BLUEPRINT wins on implementation
     - PHARMACY_BLUEPRINT wins on data shape
   If still unclear, this is a real ambiguity — not noise.

4. PROPOSE A RESOLUTION
   - Write the ambiguity in OPEN_QUESTIONS.md
   - Include: question, where it surfaced, options A/B(/C),
     recommended option with rationale, and what you'll assume
     if no decision is provided.
   - Continue building with the recommended option but flag it
     in DECISION_LOG.md as "pending confirmation".

5. ESCALATION
   - If product-impactful: post in chat, summarise, ask for
     direction.
   - If implementation-only: decide, document in DECISION_LOG.md,
     proceed.

OUTPUT:

  Ambiguity summary
  The three quotes
  Classification + precedence applied
  Proposed resolution
  Recommended next step (continue / pause for input)
```

## Context Recovery Prompt (Resume after a Break)

Paste this at the start of a fresh session when picking up after a break (a day, a week, or after context was lost).

```
You are a senior engineer resuming work on the Pharmacy Platform after
a break. Before doing anything else, restore context.

Steps:

1. Read these files in order:
     - /specs/PRODUCT_BLUEPRINT.md  (skim TOC; read §1 and §6)
     - /specs/BACKEND_BLUEPRINT.md  (skim TOC; read §3 and §27)
     - /specs/CLAUDE_CODE_PROMPTS.md (read Operating Principles §3)
     - BUILD_PROGRESS.md
     - CHANGELOG.md (last 10 entries)
     - DECISION_LOG.md (last 10 entries)
     - OPEN_QUESTIONS.md
     - RISKS.md (briefly)

2. Read these directories to understand current state:
     - app/ (tree only; understand which domains exist)
     - tests/ (count tests, note any TODO/skip)
     - migrations/versions/ (list)

3. Run a sanity check:
     - `make install`
     - `docker compose up -d mysql redis`
     - `make migrate`
     - `make test` — note any failing tests
     - `make dev` — confirm /health returns 200

4. Identify what's next:
     - Which phase is in-progress per BUILD_PROGRESS.md?
     - Which TodoWrite items are still open?
     - Any failing tests? Any open questions blocking work?

5. Produce a "where we are" summary in chat:
     - Last completed phase and what shipped
     - Current phase and progress
     - Top 3 blockers / open questions
     - Recommended next action

6. STOP. Wait for confirmation before resuming work.

If something doesn't run (tests fail, migration broken, app crashes
on start), surface it as a blocker. Do not "fix while you're here"
without acknowledgement.
```

## Refactor Prompt

Use this when a pattern that should be extracted has appeared 3+ times, or when a domain folder has grown unwieldy.

```
You are a senior engineer doing a focused refactor on the Pharmacy
Platform. Refactors are dangerous; constrain the scope hard.

Trigger / scope (one paragraph):
  [why are we refactoring; what's the current pain]

Process:

1. JUSTIFY
   - Is this refactor warranted? Or is it scratch-an-itch?
   - What concrete problem does it solve?
   - What's the cost of NOT doing it now? Of doing it later?
   - Is there a backlog item or pain in BUILD_PROGRESS.md you can
     point to?

2. SCOPE THE BLAST RADIUS
   - Which files will change?
   - Which tests will need updating?
   - Will any migration be needed? (If yes, refactor is bigger
     than expected — reconsider timing.)
   - Is there a behaviour change involved? If yes, this is not a
     pure refactor — call it out.

3. CONSTRAINTS
   - No behaviour change unless explicitly stated.
   - Tests pass before and after; same set, same green.
   - One conceptual change per PR. No "while-I-was-here" extras.
   - If a deeper issue is uncovered, file it in BUILD_PROGRESS
     backlog; don't expand scope.

4. PLAN
   - Sketch the before/after structure.
   - List the steps in order; each step keeps tests green.
   - Identify the riskiest step; consider doing it on its own
     branch first.

5. EXECUTE
   - Step by step, run tests between steps.
   - Commit per logical step (you'll squash later).

6. VERIFY
   - All tests still pass.
   - Coverage didn't drop.
   - mypy / ruff clean.
   - No imports that should now be deleted lingering.

7. DOCUMENT
   - DECISION_LOG.md if the change introduces a new pattern
     others should follow.
   - If a new pattern is introduced, consider an ADR.
   - CHANGELOG.md under "Changed".

OUTPUT:

  Diff summary
  What changed and why
  Test status before/after
  Anything to watch for
```

---

# Part 5 — Templates & What Else to Add

## Templates

### 23.1 BUILD_PROGRESS.md template

```markdown
# Build Progress

> Persistent state between sessions. Update at every phase boundary.
> If you can't tell what's next from this file, it's wrong — fix it.

## Current state

- **Active phase:** Phase X — [name]
- **Status:** in-progress / done / blocked
- **Last session:** YYYY-MM-DD
- **Next session should:** [one sentence]

## Phases

- [x] Phase 0 — Spec Comprehension & Master Plan _(done YYYY-MM-DD)_
- [ ] Phase 1 — Project Foundation
- [ ] Phase 2 — Database Foundation & Alembic
- [ ] Phase 3 — Core Infrastructure
- [ ] Phase 4 — Identity & Authentication
- [ ] Phase 5 — Catalog Domain & Admin Catalog API
- [ ] Phase 6 — Inventory Domain & Admin Inventory API
- [ ] Phase 7 — Customer Discovery
- [ ] Phase 8 — Cart, Checkout & Place-Order (FEFO)
- [ ] Phase 9 — Admin Order Lifecycle, Reports & Audit
- [ ] Phase 10 — Integrations: SMS, Payments, Storage
- [ ] Phase 11 — Background Jobs & Scheduled Tasks
- [ ] Phase 12 — Hardening & Launch Readiness

## Smoke test recipes

> Concrete commands that prove the system works at each milestone.
> Update as new flows ship.

### After Phase 1
```bash
make install
docker compose up -d mysql redis
make dev
curl localhost:8000/health   # → {"status":"ok"}
```

### After Phase 4
```bash
# OTP request → verify → /me
curl -X POST localhost:8000/api/v1/auth/otp/request \
  -H 'Content-Type: application/json' \
  -d '{"phone":"+996700123456"}'
# read OTP from log, then:
curl -X POST localhost:8000/api/v1/auth/otp/verify \
  -H 'Content-Type: application/json' \
  -d '{"phone":"+996700123456","code":"123456"}'
# → tokens; use access:
curl localhost:8000/api/v1/me \
  -H 'Authorization: Bearer <access>'
```

### After Phase 8
```bash
# (continued from Phase 4)
# Browse, add to cart, checkout COD
...
```

## Backlog (deferred items)

- [ ] Item — when surfaced (phase) — defer to (phase or "post-MVP")

## Active blockers

- None / list

## In-progress TodoWrite items

> Synced from active session. Cleared when phase completes.
```

### 23.2 DECISION_LOG.md template

```markdown
# Decision Log

> Non-obvious choices and their rationale. Future-you reading this should
> understand why something was done a particular way without re-deriving
> it. Append-only; never edit past entries.

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

### 2026-XX-XX — Use uv as package manager
**Phase:** 1
**Context:** BACKEND_BLUEPRINT §2 lists uv; team had no prior preference.
**Decision:** uv with pyproject.toml.
**Alternatives considered:** poetry, pip-tools.
**Rationale:** uv is significantly faster, has good Docker layer
caching support, and the lockfile (uv.lock) format is standard.
**Trade-offs:** Newer than poetry; team needs to learn. CI cache
behaviour slightly different.
**Reversibility:** Easy — both produce a lockfile and respect
pyproject.toml.
**References:** BACKEND §2; commit abc1234.

### 2026-XX-XX — Byte-swap UUIDs in GUID type
**Phase:** 2
...
```

### 23.3 CHANGELOG.md template (Keep a Changelog)

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Phase 1: project skeleton, FastAPI app with /health endpoint
- Phase 2: SQLAlchemy async engine, Alembic migrations

### Changed
- (none yet)

### Deprecated
- (none yet)

### Removed
- Phase 4: removed temporary `ping` table from Phase 2

### Fixed
- (none yet)

### Security
- (none yet)

---

## [1.0.0-rc1] - 2026-XX-XX

### Added
- Initial release candidate. All Phase 1–12 features.
- Customer-facing storefront API (catalog, search, cart, checkout)
- Admin API (catalog management, inventory, orders, reports)
- Background workers via ARQ
- SMS, payment, and storage integrations

### Security
- argon2id password hashing
- JWT access/refresh tokens with rotation
- Admin sessions with optional TOTP MFA
- All admin mutations audited
- Rate limiting on OTP request and login
```

### 23.4 ADR template (`docs/adr/0001-title.md`)

```markdown
# ADR 0001: Title in present tense

- **Status:** Proposed | Accepted | Superseded by ADR-NNNN
- **Date:** YYYY-MM-DD
- **Deciders:** name(s)

## Context

What is the issue we're addressing? Include enough background that someone
new to the project can understand the question without reading the whole
spec.

## Decision

What did we decide?

## Consequences

### Positive
- …

### Negative
- …

### Neutral
- …

## Alternatives considered

### Alternative 1
Description and why not chosen.

### Alternative 2
Description and why not chosen.

## References

- Spec sections
- Related ADRs
- External links
```

### 23.5 Conventional Commits convention

Every commit follows:

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat` — new feature visible to users or operators
- `fix` — bug fix
- `refactor` — code change that doesn't add features or fix bugs
- `perf` — performance improvement
- `test` — adding or correcting tests
- `docs` — documentation only
- `build` — build system, dependencies, Docker, CI
- `chore` — repo housekeeping (e.g., `.gitignore`)
- `revert` — reverts a previous commit

**Scopes:** match the domain or layer. Examples: `auth`, `catalog`, `orders`, `inventory`, `infra`, `ci`, `db`.

**Subject:** imperative mood, ≤ 72 chars, no period.

**Body (optional):** explain WHY. The diff explains WHAT.

**Footer (optional):**
- `BREAKING CHANGE:` — describe the break
- `Refs: F-CAT-003, ADR-0007` — references

**Examples:**

```
feat(auth): add OTP request endpoint with per-phone rate limiting

Implements F-AUTH-001. Per BACKEND §14.1, codes are 6 digits, 5-min TTL,
hashed with HMAC-SHA256 + pepper. Rate limits: 1/60s, 3/15m per phone.

Refs: F-AUTH-001, BACKEND §14.1
```

```
fix(orders): release stock reservation on customer cancel

When a customer cancelled a pending order, branch_products.reserved_quantity
was not decremented because the cancel path forgot to call
InventoryService.release_reservations().

Adds regression test in tests/integration/test_order_cancel.py.

Refs: F-ORD-002
```

```
refactor(catalog): extract slug generation to SlugService

Slug generation logic was duplicated across product create and bulk
import paths. Extracted to a single service with the same behaviour.

No behaviour change. Tests updated to use the service directly.
```

### 23.6 PR template (`.github/pull_request_template.md`)

```markdown
## Summary

[One paragraph: what changed and why]

## Phase

This PR is part of: **Phase N — [name]**

## Spec references

- PRODUCT_BLUEPRINT: §X.Y
- BACKEND_BLUEPRINT: §A.B
- PHARMACY_BLUEPRINT: §M.N

## Feature IDs

- F-AAA-NNN
- F-BBB-NNN

## Definition of Done

- [ ] Implementation matches the phase prompt
- [ ] All listed tests pass locally
- [ ] mypy --strict clean
- [ ] ruff clean
- [ ] BACKEND §27 conventions checklist
- [ ] PRODUCT §26 conventions checklist
- [ ] BUILD_PROGRESS.md updated
- [ ] CHANGELOG.md updated
- [ ] DECISION_LOG.md updated (if applicable)

## How to verify

```
[paste exact commands a reviewer should run]
```

## Risks / things to watch

- …

## Out of scope

- … (deferred to phase X)
```

---

## What Else to Add Before You Start Coding

> The user asked: *"what do you think what else we might add to the prompts?"*
>
> Honest answer: the prompt suite above will get you a working backend MVP. But there are seams where adding more upfront pays off vs. discovering the gap mid-build. Below is what I'd add — ranked by leverage.

### 24.1 High leverage — add before Phase 0

These are cheap to write now, expensive to retrofit.

#### A. A `CLAUDE.md` project-rules file at repo root

Claude Code reads `CLAUDE.md` automatically on every session. It should contain:
- The Operating Principles (§3 of this doc)
- The Conventional Commits convention (§23.5)
- A pointer to `/specs` and `BUILD_PROGRESS.md`
- The "always re-read these on resume" instruction

Without this, every new session starts with cold context. With it, even a fresh Claude knows the rules.

**Suggested addition:** create `CLAUDE.md` as part of Phase 0's deliverables. ~150 lines.

#### B. A test-data fixtures spec

The build phases assume seeded data exists. Right now each phase produces its own. Better: a single `dev/fixtures/` with:
- 2 branches (Bishkek Central, Bishkek Asanbai)
- 5 manufacturers (real KG-distributed brands)
- 30 active ingredients
- 12 symptoms
- 50 products spanning every category from PRODUCT §5.1
- 200 inventory_batches with varied expiry dates (some near-expiry to test the workflow)
- 10 customers
- 5 admin users (one per role)
- 30 orders in various states

**Suggested addition:** a "Phase 5.5 — Seed Fixtures" mini-phase between Phase 5 and 6, OR an annex to Phase 5's prompt. Each subsequent phase's tests can rely on these.

#### C. An API contract document (or commit to OpenAPI as the source of truth)

Right now, the API surface is described across the three blueprints. A consolidated `API_CONTRACT.md` (or just letting OpenAPI auto-gen with strict tagging discipline) prevents inconsistencies. Pick one:

- **Option A:** OpenAPI from FastAPI is the source of truth; review religiously each phase.
- **Option B:** Hand-written `API_CONTRACT.md` checked against OpenAPI in CI.

I'd pick A and add a Phase 12 task: "Run OpenAPI through a linter (Spectral) and fix all warnings."

### 24.2 Medium leverage — add as separate spec docs

These deserve their own blueprint files when you decide to build them.

#### D. **Frontend Blueprint** (Next.js storefront + Admin UI)

The current three blueprints are backend-only. The storefront and admin panels need their own spec covering:
- Component architecture (server components vs client; design system)
- Auth flow on the client (token storage, refresh, multi-device)
- Cart persistence strategy (localStorage + server sync)
- i18n on the client (next-intl?)
- Image optimisation (next/image vs CDN-side)
- Admin app: separate domain? Shared codebase?
- State management (server actions + minimal client state, or Zustand?)
- Real-time order-status (SSE? polling?)

**Suggested:** ~1,500–2,000 lines. I'd write this before starting frontend work — same approach as the backend.

#### E. **DevOps & Deployment Blueprint**

Phase 12 covers deployment in the prompt, but a separate blueprint would specify:
- Provider choice (Hetzner / DigitalOcean / Yandex Cloud — and *why*)
- Single-VPS topology vs HA from day one
- Load balancer / Caddy vs Nginx vs Traefik
- TLS automation (Let's Encrypt)
- CI/CD pipeline (GitHub Actions runners — self-hosted on a small VPS or hosted?)
- Secrets management (Vault, Doppler, age-encrypted env files?)
- Backup strategy (daily, weekly retention; encrypted; cross-region copy)
- Monitoring stack (Grafana Cloud free tier? Self-hosted Prom + Grafana?)
- Incident runbook structure
- On-call / paging (PagerDuty? Healthchecks.io?)
- Cost target and tracking

**Suggested:** ~1,000 lines. Written when ready to deploy.

#### F. **QA & Test Plan Blueprint**

A separate doc enumerating *manual* test scenarios beyond automated tests:
- Cross-device testing (iOS Safari, Android Chrome, desktop)
- SMS deliverability test (real numbers, off-hours)
- Payment gateway sandbox + production-flip checklist
- Cold-chain item delivery test in summer
- Bilingual usability test (RU / KY)
- Accessibility audit (axe + manual)
- Load test scenarios with concrete RPS targets

**Suggested:** ~500–800 lines.

### 24.3 Low leverage — write only if you hit the pain

#### G. Onboarding prompt for new developers
Useful if you grow the team. Becomes a `docs/ONBOARDING.md` that walks a new dev (human or AI) through the project in a structured way — read-this, run-this, build-this-tiny-thing.

#### H. Incident response prompt
Useful when you've launched and something breaks at 2am. Walks through: triage, mitigate, document, post-mortem.

#### I. Spec evolution prompt
For when the product team wants to change something post-launch. Covers: how to update the blueprint, how to migrate data, how to coordinate a behaviour change without surprising customers.

### 24.4 Concrete recommendation

If I were starting this project tomorrow with the four files we have, I'd add **only these two** before Phase 0:

1. **`CLAUDE.md` at repo root** — 150-line project rules file. Makes every session start hot.
2. **A "Phase 5.5 — Seed Fixtures" prompt** — ensures every subsequent phase has the test data it expects.

Everything else (frontend, devops, QA blueprints) gets added when you actually need it. Writing them speculatively is overhead.

### 24.5 Things deliberately NOT in the prompt suite

I considered and rejected:

- **Per-phase time estimates beyond rough ranges.** Estimates are usually wrong; phase boundaries are stable. Keep the boundaries firm and let timing flex.
- **Detailed test counts per phase.** Quantity ≠ quality. The DoD names the categories of test required; counting is busywork.
- **Code style enforcement in prompt text.** Ruff and mypy enforce style. Don't paste rules into prompts.
- **Demo / showcase prompts.** A milestone is when tests pass and the smoke recipe runs. Demos for stakeholders are out of scope for the build prompts.
- **A "creative" prompt for things like product copy or naming.** PRODUCT §21 already has the copy library. There's nothing creative left.

---

*Document version 1.0 — Claude Code prompts for the Pharmacy Platform build. Companion to PHARMACY_BLUEPRINT.md, BACKEND_BLUEPRINT.md, and PRODUCT_BLUEPRINT.md.*

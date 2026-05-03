# Contributing

> Read `CLAUDE.md` first if you're using an AI assistant. The "sacred
> invariants" + "mechanical overrides" sections are non-negotiable.

## Setup

```bash
brew install uv                  # macOS; Linux: curl -LsSf https://astral.sh/uv/install.sh | sh
make install                     # uv sync — Python 3.12 + deps into .venv
make docker-up                   # mysql:8.4 + redis:7-alpine
cp .env.example .env             # then fill in any local secrets
make migrate                     # alembic upgrade head
make seed                        # load dev fixtures
make dev                         # uvicorn on :8000 with reload
```

Verify: `curl localhost:8000/health` returns `{"status":"ok",...}`.

## Branch + commit conventions

- **Branch naming**: `phase-N-short-description` for spec'd phases,
  `fix/short-description` for bugs, `chore/short-description` for housekeeping.
- **Conventional Commits**: `type(scope): subject` — `feat`, `fix`, `refactor`,
  `test`, `docs`, `chore`, `build`. Body explains WHY; the diff explains WHAT.
  Reference feature IDs and spec sections in the body.
- **Squash merges only.** One PR = one feature.
- **PR template** (`.github/pull_request_template.md`) — fill it out, the DoD
  checklist is not decorative.

## Pre-commit gates

```bash
make lint        # ruff check + format check
make type        # mypy --strict
make test        # pytest
make pre-commit  # all hooks (trailing-whitespace, EOF, yaml, ruff, mypy)
```

CI runs the same gates. Failing CI on a PR is normal; iterate locally first.

## Adding a new endpoint

1. **Schema** — add request/response Pydantic models in `app/domain/<context>/schemas.py`.
2. **Service method** — orchestrate via `app/domain/<context>/services.py`.
   Repositories are thin and never commit; services own transactions.
3. **Route** — `app/api/v1/<thing>.py` (customer) or `admin_v1/<thing>.py`
   (admin). Use `_AdminGuard` / `require_role(...)` / `require_branch_access`.
4. **DI** — wire factories in `app/api/deps.py` if a new service.
5. **Test** — unit (mock repos) + integration (real DB) + at least one E2E
   (`tests/e2e/`).
6. **Audit log** — every admin mutation writes via `AdminAuditLogService`.
7. **Run `make pre-commit`** before committing.

## Adding a new background job

1. Body in `app/workers/<module>.py` per BACKEND §17.3 pattern: open
   `session_scope`, call domain services, log structured event.
2. Register in `app/workers/settings.py`'s `functions=[...]` (on-demand) or
   `cron_jobs=[...]` (scheduled). For cron, add the inline KG→UTC mapping
   comment AND the entry in `KG_TO_UTC_HOUR_MAPPING`.
3. Add a unit test using the `worker_session_scope` fixture.
4. Test enqueue end-to-end via the Phase 11 `arq_round_trip` pattern.

## Adding a new dependency

1. Justify in chat (why none of the existing libs fit).
2. Update `pyproject.toml`, run `uv sync`, commit `uv.lock`.
3. Log the choice in `DECISION_LOG.md`.
4. Update `BACKEND §2`'s pinned-versions list if it's a top-level dep.

## Updating the schema

1. Modify `app/domain/<context>/models.py`.
2. `uv run alembic revision --autogenerate -m "<change>"`.
3. Hand-edit the autogen output: strip spurious `alter_column` noise, add
   `import app.core.types` if GUID columns appear, replace string interpolation
   with `op.execute(text(...))` for CHECKs that need them.
4. **Verify round-trip**: `make migrate && alembic downgrade -1 && alembic upgrade head`.
5. Document any non-obvious schema decisions in `DECISION_LOG.md`.

## Specs are read-only during build phases

`/specs/{PRODUCT,PHARMACY,BACKEND}_BLUEPRINT.md` + `CLAUDE_CODE_PROMPTS.md`
are NOT edited during implementation. If a spec instruction looks wrong,
surface in chat with the reasoning; the human team updates the spec.

## What goes where

- **Domain logic** → `app/domain/<context>/`. Models, repositories, services,
  schemas.
- **Routes** → `app/api/v1/` (customer) or `app/api/admin_v1/` (admin) or
  `app/api/webhooks/` (signed inbound). Routes are thin — only HTTP concerns.
- **Cross-cutting infra** → `app/core/`. Never put domain logic here.
- **Integrations** → `app/integrations/<provider>/{base,real,fake,factory}.py`.
- **Workers** → `app/workers/<job>.py`.

## When you're stuck

- Specs disagree → precedence is PRODUCT (behaviour) > BACKEND (impl) >
  PHARMACY (data shape).
- Specs silent → log in `OPEN_QUESTIONS.md` with proposed default; continue
  with the default; mark `DECISION_LOG.md` "pending confirmation".
- Spec wrong → surface in chat with reasoning; don't silently work around.
- Library behaviour different from training data → web search current docs;
  verify with a test.

.DEFAULT_GOAL := help
.PHONY: help install dev worker test test-fast test-e2e lint type fmt \
        migrate revision \
        docker-up docker-down docker-up-test docker-down-test \
        shell-mysql shell-redis pre-commit seed

PYTHON := uv run python
PYTEST := uv run pytest

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ─── Setup ────────────────────────────────────────────────────────────────────
install:  ## uv sync (incl. dev deps)
	uv sync

# ─── Run ──────────────────────────────────────────────────────────────────────
dev: docker-up  ## Bring up infra + run API with hot reload on :8000
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

worker:  ## Run ARQ worker (Phase 11+)
	uv run arq app.workers.settings.WorkerSettings

worker-once:  ## Force-run a single scheduled job by name. Usage: make worker-once JOB=expire_batches
	@if [ -z "$(JOB)" ]; then echo "Usage: make worker-once JOB=<name>"; exit 1; fi
	uv run python -m app.workers.run_once $(JOB)

security-audit:  ## Audit dependencies for known CVEs (pip-audit).
	uv run --with pip-audit pip-audit --skip-editable

backup-local:  ## Run the backup script to a local /tmp file (smoke test).
	bash bin/backup_db.sh /tmp/pharmacy-backup-$$(date -u +%Y%m%dT%H%M%SZ).sql.gz

# ─── Quality ──────────────────────────────────────────────────────────────────
lint:  ## ruff check + format check
	uv run ruff check app tests
	uv run ruff format --check app tests

type:  ## mypy --strict
	uv run mypy app

fmt:  ## Auto-fix lint issues and apply formatter
	uv run ruff check --fix app tests
	uv run ruff format app tests

# ─── Tests ────────────────────────────────────────────────────────────────────
test:  ## Run full test suite
	$(PYTEST)

test-fast:  ## Unit tests only (no DB / external)
	$(PYTEST) -m "unit"

test-e2e:  ## End-to-end tests (full HTTP stack)
	$(PYTEST) -m "e2e"

# ─── Docker / infra ───────────────────────────────────────────────────────────
docker-up:  ## Bring up dev MySQL + Redis
	docker compose up -d mysql redis

docker-down:  ## Stop dev services (keep volumes)
	docker compose down

docker-up-test:  ## Bring up test MySQL on :3307 (tmpfs)
	docker compose --profile test up -d mysql-test redis

docker-down-test:  ## Stop test services
	docker compose --profile test down

shell-mysql:  ## MySQL CLI in dev container
	docker compose exec mysql mysql -upharmacy -ppharmacy pharmacy

shell-redis:  ## Redis CLI in dev container
	docker compose exec redis redis-cli

# ─── Migrations (Phase 2+) ────────────────────────────────────────────────────
migrate:  ## alembic upgrade head
	uv run alembic upgrade head

revision:  ## Create a migration. Usage: make revision m="add product table"
	uv run alembic revision --autogenerate -m "$(m)"

# ─── Hooks ────────────────────────────────────────────────────────────────────
pre-commit:  ## Install pre-commit hooks and run on all files
	uv run pre-commit install
	uv run pre-commit run --all-files

# ─── Seeds (Phase 5+) ─────────────────────────────────────────────────────────
seed:  ## Load dev fixtures (Phase 5+)
	uv run python -m dev.fixtures.seed

.PHONY: install test lint format format-check typecheck migration-check web-test web-typecheck web-lint web-build web-e2e backend-verify web-verify verify services-up services-down run-api

PYTHON := .venv/bin/python
RUFF := .venv/bin/ruff
MYPY := .venv/bin/mypy
ALEMBIC := .venv/bin/alembic

install:
	uv sync --all-groups

test:
	$(PYTHON) -m pytest

lint:
	$(RUFF) check src tests migrations

format:
	$(RUFF) format src tests migrations

format-check:
	$(RUFF) format --check src tests migrations

typecheck:
	$(MYPY) src

migration-check:
	rm -f /tmp/family-recipe-agent-migration.db
	RECIPE_AGENT_DATABASE_URL=sqlite:////tmp/family-recipe-agent-migration.db $(ALEMBIC) upgrade head

web-test:
	pnpm --dir web test

web-typecheck:
	pnpm --dir web typecheck

web-lint:
	pnpm --dir web lint

web-build:
	pnpm --dir web build

web-e2e:
	pnpm --dir web exec playwright test tests/e2e/core-flow.spec.ts

backend-verify: format-check lint typecheck test migration-check

web-verify: web-test web-typecheck web-lint web-build web-e2e

verify: backend-verify web-verify

services-up:
	docker compose -f infra/compose.yaml up -d postgres redis minio minio-init

services-down:
	docker compose -f infra/compose.yaml down

run-api:
	uv run uvicorn recipe_agent.app:app --reload --host 0.0.0.0 --port 8000

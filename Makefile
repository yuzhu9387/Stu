.PHONY: install test lint format typecheck verify services-up services-down run-api

install:
	uv sync --all-groups

test:
	uv run pytest

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

typecheck:
	uv run mypy src

verify: lint typecheck test

services-up:
	docker compose -f infra/compose.yaml up -d postgres redis minio minio-init

services-down:
	docker compose -f infra/compose.yaml down

run-api:
	uv run uvicorn recipe_agent.app:app --reload --host 0.0.0.0 --port 8000

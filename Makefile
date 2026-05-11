.PHONY: help install install-spacy lint type test test-integration test-live migrate seed seed-light up down logs decrypt-env

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' Makefile | awk 'BEGIN{FS=":.*?## "} {printf "  %-18s %s\n", $$1, $$2}'

install:  ## Sync dev deps with uv (run inside server/)
	cd server && uv sync

install-spacy:  ## Download the spaCy NER model used by the sanitisation pipeline
	cd server && uv run python -m spacy download en_core_web_sm

lint:  ## Run ruff
	cd server && uv run ruff check . && uv run ruff format --check .

type:  ## Run mypy
	cd server && uv run mypy soundings

test:  ## Run unit tests (no live APIs, no DB required for non-integration)
	cd server && uv run pytest -m "not live and not integration"

test-integration:  ## Run integration tests (needs running docker compose)
	cd server && uv run pytest -m integration

test-live:  ## Run live-API tests (nightly cron only)
	cd server && uv run pytest -m live

up:  ## Bring up the docker compose stack
	docker compose -f infra/docker-compose.yml --project-directory . up -d

down:  ## Tear down the stack
	docker compose -f infra/docker-compose.yml --project-directory . down

logs:  ## Tail logs
	docker compose -f infra/docker-compose.yml --project-directory . logs -f

migrate:  ## Run alembic upgrade head against running stack
	docker compose -f infra/docker-compose.yml --project-directory . exec server alembic upgrade head

seed:  ## Full geography + catalogue seed (~1 hour)
	docker compose -f infra/docker-compose.yml --project-directory . exec server python -m soundings.seed.run --full

seed-light:  ## Dev seed (single LTLA, ~5 min)
	docker compose -f infra/docker-compose.yml --project-directory . exec server python -m soundings.seed.run --light

decrypt-env:  ## Decrypt .env from soundings-ops (placeholder until soundings-ops exists)
	@echo "TODO: implement once soundings-ops repo exists"

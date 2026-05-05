# Soundings v1 — Phase 0 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stand up the repo, CI, Docker Compose, the Postgres schema, the catalogue loader, and the geography spine. Phase 0 ends when a known UK postcode can be resolved to its containing LSOA, MSOA, LTLA, UTLA, region, country, ward, and Westminster constituency, end-to-end against the live `docker compose up` stack — with all checks green.

**Architecture:** Per `docs/plans/2026-05-05-soundings-v1-design.md`. FastAPI server + PostGIS Postgres in Docker Compose. SQLAlchemy 2 async + Alembic migrations. Two adapters land here: `ons.geography` (loader-mode, seeds the spine from ONS Open Geography Portal) and `postcodes.io` (passthrough, with TTL cache). No MCP tool surface in Phase 0 — that's Phase 1. Phase 0 stops at an internal `GeographyService` that the orchestrator will call.

**Tech Stack:** Python 3.12, `uv`, FastAPI, SQLAlchemy 2 (async) + asyncpg, Alembic, Pydantic v2, httpx, aiolimiter, pytest + pytest-vcr, ruff, mypy, structlog, PostGIS 16, Docker Compose, Caddy 2, GitHub Actions.

**Estimated scope:** ~40 bite-sized tasks across 7 blocks. Each task is 2–10 minutes of work. Total: roughly one focused week.

**Prerequisites Tom needs to do once before starting:**
- Create the public GitHub repo `<github-org>/soundings` (org TBC — `dataforaction-tom` or a Good Ship org). Set licence files in repo settings to AGPL-3.0.
- Create the private companion repo `<github-org>/soundings-ops`.
- On the dev machine: install `uv` (https://github.com/astral-sh/uv), Docker Desktop, and Python 3.12 (uv handles this).
- On the Mac mini: confirm `cloudflared` config path and existing ingress rules — needed for the smoke deploy at end of Phase 0.

---

## Conventions used in this plan

- **TDD throughout.** Every task that adds behaviour is: write failing test → run to confirm fail → implement minimum → run to confirm pass → commit. Pure scaffolding/config tasks (Dockerfiles, CI yaml) skip the test step but still commit per task.
- **Commits per task** with conventional-commits prefixes (`feat`, `chore`, `test`, `refactor`, `docs`, `ci`).
- **Exact file paths.** All paths are relative to repo root unless prefixed `/`.
- **All commands assume PowerShell on Windows or zsh on Mac mini.** Docker commands work on both. Where they differ, both are shown.

---

## Block A — Repo scaffolding (Tasks 1–5)

### Task 1: Add three licence files

**Files:**
- Create: `LICENSE-AGPL-3.0` (the AGPL-3.0 text — applies to `server/` code)
- Create: `LICENSE-CC0` (CC0 text — applies to `catalogue/` and any schema files)
- Create: `LICENSE-CC-BY-4.0` (CC BY 4.0 text — applies to `docs/` specs)
- Create: `LICENSE.md` — a short index file pointing to which licence applies where

**Steps:**
1. Download the three licence texts verbatim from `https://www.gnu.org/licenses/agpl-3.0.txt`, `https://creativecommons.org/publicdomain/zero/1.0/legalcode.txt`, and `https://creativecommons.org/licenses/by/4.0/legalcode.txt`.
2. Write `LICENSE.md` with this content:

```markdown
# Licensing

Soundings is licensed under three different licences depending on the content type:

| Path | Licence | File |
|---|---|---|
| `server/`, `ui/`, `infra/`, `scripts/` | AGPL-3.0-only | LICENSE-AGPL-3.0 |
| `catalogue/`, any `*.json`/`*.yaml` schema | CC0-1.0 | LICENSE-CC0 |
| `docs/` (specs and plans) | CC BY 4.0 | LICENSE-CC-BY-4.0 |
```

3. Commit:

```bash
git add LICENSE-AGPL-3.0 LICENSE-CC0 LICENSE-CC-BY-4.0 LICENSE.md
git commit -m "chore: add AGPL-3.0, CC0, CC BY 4.0 licence files"
```

### Task 2: Replace the placeholder README with a real one

**Files:**
- Modify: `README.md`

**Steps:**
1. Replace the template README with this content:

```markdown
# Soundings

> *Taking the measure of local need.*

An open insight commons for understanding what's happening in places across the UK. A single MCP server wraps UK open data behind question-shaped tools, and every consented question becomes part of a public corpus.

See [`docs/`](./docs/) for the full v1–v3 specs and design docs.

## Status

Phase 0 of v1 — repo and geography spine. See [`docs/plans/2026-05-05-soundings-v1-design.md`](./docs/plans/2026-05-05-soundings-v1-design.md) for the implementation design and [`docs/plans/2026-05-05-soundings-v1-phase-0-plan.md`](./docs/plans/2026-05-05-soundings-v1-phase-0-plan.md) for the current build plan.

## Quick start (dev)

```bash
make decrypt-env       # generate .env from soundings-ops (private)
docker compose up -d
make migrate
make seed-light        # ~5 min, single LTLA worth of data
```

## Licensing

See [LICENSE.md](./LICENSE.md). Server code is AGPL-3.0; schema is CC0; specs are CC BY 4.0.

## Maintained by

[The Good Ship](https://good-ship.co.uk).
```

2. Commit: `git commit -am "docs: real README with project context and quick-start"`

### Task 3: Move spec docs into `docs/`, indicators.yaml into `catalogue/`

**Files:**
- Move: `v1-orchestration-and-capture.md` → `docs/v1-orchestration-and-capture.md`
- Move: `v1.5-just-in-time-interfaces.md` → `docs/v1.5-just-in-time-interfaces.md`
- Move: `v2-context-layer.md` → `docs/v2-context-layer.md`
- Move: `v3-contribution-layer.md` → `docs/v3-contribution-layer.md`
- Move: `indicators.yaml` → `catalogue/indicators.yaml`
- Move: `soundings.yaml` → `examples/soundings.yaml`
- Move: `soundings-minimal.yaml` → `examples/soundings-minimal.yaml`

**Steps:**
1. `mkdir -p catalogue examples`
2. `git mv` each file as listed above (use `git mv` so history is preserved).
3. Update internal cross-links in spec docs that reference siblings (e.g. `./README.md` should become `../README.md`). Open each spec, search for `](.` links, fix.
4. Commit: `git commit -m "chore: relocate specs into docs/, catalogue, and examples per design"`

### Task 4: Bootstrap the Python project with `uv`

**Files:**
- Create: `server/pyproject.toml`
- Create: `server/.python-version` containing `3.12`
- Create: `server/soundings/__init__.py` containing `__version__ = "0.0.1"`
- Create: `server/README.md` (one-paragraph "this is the FastAPI + MCP server")
- Create: `.gitignore` additions for Python: `__pycache__/`, `*.pyc`, `.venv/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `htmlcov/`, `.coverage`

**`server/pyproject.toml`:**

```toml
[project]
name = "soundings"
version = "0.0.1"
description = "Soundings server — MCP + FastAPI orchestration over UK open data"
requires-python = ">=3.12"
license = { file = "../LICENSE-AGPL-3.0" }
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "mcp>=1.2",
    "sqlalchemy[asyncio]>=2.0.36",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "pydantic>=2.10",
    "pydantic-settings>=2.6",
    "httpx>=0.28",
    "aiolimiter>=1.2",
    "geoalchemy2>=0.16",
    "structlog>=24.4",
    "pyyaml>=6.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-vcr>=1.0.2",
    "vcrpy>=6.0",
    "ruff>=0.8",
    "mypy>=1.13",
    "types-pyyaml",
    "httpx>=0.28",      # for TestClient
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "N", "ASYNC", "S", "RUF"]
ignore = ["S101"]      # asserts in tests are fine

[tool.mypy]
strict = true
python_version = "3.12"
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "live: hits real upstream APIs; nightly only",
    "integration: requires running Postgres",
]
```

**Steps:**
1. From repo root: `cd server && uv sync` — should create `.venv` and install everything.
2. Run `uv run python -c "import soundings; print(soundings.__version__)"` — expect `0.0.1`.
3. Commit:

```bash
git add server/pyproject.toml server/uv.lock server/.python-version server/soundings/__init__.py server/README.md .gitignore
git commit -m "chore: bootstrap server package with uv, ruff, mypy, pytest"
```

### Task 5: Add a top-level Makefile

**Files:**
- Create: `Makefile`

**Content:**

```makefile
.PHONY: help install lint type test test-live migrate seed seed-light up down logs decrypt-env

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' Makefile | awk 'BEGIN{FS=":.*?## "} {printf "  %-18s %s\n", $$1, $$2}'

install:  ## Sync dev deps with uv (run inside server/)
	cd server && uv sync

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
	docker compose -f infra/docker-compose.yml up -d

down:  ## Tear down the stack
	docker compose -f infra/docker-compose.yml down

logs:  ## Tail logs
	docker compose -f infra/docker-compose.yml logs -f

migrate:  ## Run alembic upgrade head against running stack
	docker compose -f infra/docker-compose.yml exec server alembic upgrade head

seed:  ## Full geography + catalogue seed (~1 hour)
	docker compose -f infra/docker-compose.yml exec server python -m soundings.seed.run --full

seed-light:  ## Dev seed (single LTLA, ~5 min)
	docker compose -f infra/docker-compose.yml exec server python -m soundings.seed.run --light

decrypt-env:  ## Decrypt .env from soundings-ops (placeholder until soundings-ops exists)
	@echo "TODO: implement once soundings-ops repo exists"
```

**Steps:**
1. `make help` should print the targets with descriptions. (Note: Windows users may need `make` via Git Bash or WSL; Mac mini will be the primary user of these targets.)
2. Commit: `git commit -am "chore: add top-level Makefile with operator-facing targets"`

---

## Block B — Docker, Postgres, and the database connection layer (Tasks 6–10)

### Task 6: Write `Dockerfile.server`

**Files:**
- Create: `infra/Dockerfile.server`
- Create: `.dockerignore`

**`infra/Dockerfile.server`:**

```dockerfile
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5.10 /uv /usr/local/bin/uv

# OS deps for asyncpg, geo libs, healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server/pyproject.toml server/uv.lock /app/server/
RUN cd /app/server && uv sync --frozen --no-dev --no-install-project

COPY server/ /app/server/
RUN cd /app/server && uv sync --frozen --no-dev

ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app/server

EXPOSE 8000
CMD ["uvicorn", "soundings.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**`.dockerignore`:**

```
.git
.venv
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
htmlcov
.coverage
docs
ui/node_modules
ui/.astro
```

**Steps:**
1. Verify image builds: `docker build -f infra/Dockerfile.server -t soundings-server:dev .` — expect success.
2. Commit: `git commit -am "chore(infra): add Dockerfile.server and .dockerignore"`

### Task 7: Write `docker-compose.yml` with Postgres + server (no UI yet)

**Files:**
- Create: `infra/docker-compose.yml`
- Create: `.env.example`

**`infra/docker-compose.yml`:**

```yaml
name: soundings

services:
  postgres:
    image: postgis/postgis:16-3.4
    restart: unless-stopped
    environment:
      POSTGRES_DB: soundings
      POSTGRES_USER: soundings
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./initdb:/docker-entrypoint-initdb.d:ro
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "soundings", "-d", "soundings"]
      interval: 5s
      timeout: 3s
      retries: 10

  server:
    build:
      context: ..
      dockerfile: infra/Dockerfile.server
    depends_on:
      postgres:
        condition: service_healthy
    env_file:
      - ../.env
    environment:
      DATABASE_URL: "postgresql+asyncpg://soundings:${POSTGRES_PASSWORD}@postgres:5432/soundings"
    ports:
      - "127.0.0.1:8000:8000"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/healthz"]
      interval: 10s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
```

**`.env.example`:**

```
# Copy to .env (git-ignored). For dev, any password works.
POSTGRES_PASSWORD=changeme-locally

# Soundings runtime
SOUNDINGS_LOG_LEVEL=info
SOUNDINGS_ENV=dev

# Adapter API keys (Phase 0 needs none of these — added in later phases)
# CHARITY_COMMISSION_API_KEY=
# DWP_STATXPLORE_KEY=
# NOMIS_API_KEY=
```

**Steps:**
1. `cp .env.example .env` (or generate one for dev).
2. `make up` — both containers should reach healthy state within ~30s.
3. `docker compose -f infra/docker-compose.yml ps` — expect `postgres (healthy)` and `server` will be unhealthy until `/healthz` exists; that's fine for now.
4. `make down`.
5. Commit: `git commit -am "chore(infra): add docker-compose with postgres + server services"`

### Task 8: Add Postgres schema bootstrap (`initdb` SQL)

**Files:**
- Create: `infra/initdb/00-extensions.sql`
- Create: `infra/initdb/01-schemas.sql`

**`00-extensions.sql`:**

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;          -- for fuzzy place name matching
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

**`01-schemas.sql`:**

```sql
CREATE SCHEMA IF NOT EXISTS geography;
CREATE SCHEMA IF NOT EXISTS catalogue;
CREATE SCHEMA IF NOT EXISTS data;
CREATE SCHEMA IF NOT EXISTS cache;
CREATE SCHEMA IF NOT EXISTS corpus;
```

**Steps:**
1. `make down -v` if you have an existing volume — these scripts only run on first init.
2. `docker volume rm soundings_pgdata` if needed.
3. `make up` — Postgres logs should show `running … 00-extensions.sql` and `01-schemas.sql`.
4. Verify: `docker compose -f infra/docker-compose.yml exec postgres psql -U soundings -d soundings -c "\dn"` — expect five schemas plus `public`.
5. Commit: `git commit -am "chore(infra): add postgis + schema bootstrap initdb scripts"`

### Task 9: Add the database connection layer (TDD)

**Files:**
- Create: `server/soundings/db/__init__.py`
- Create: `server/soundings/db/engine.py`
- Create: `server/soundings/core/config.py`
- Create: `server/tests/conftest.py`
- Create: `server/tests/test_db_connection.py`

**Step 1: Write the failing integration test.**

**`server/tests/test_db_connection.py`:**

```python
import pytest
from sqlalchemy import text

from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def test_can_connect_and_query_postgis_version():
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT postgis_version()"))
        version = result.scalar_one()
        assert version is not None
        assert "POSTGIS" in version.upper()
```

**Step 2: Run it (expecting failure).**

```bash
make up
make migrate            # will fail — no alembic yet, fine for now
cd server && uv run pytest tests/test_db_connection.py -v
```

Expect: `ImportError: cannot import name 'get_engine'`.

**Step 3: Write minimum implementation.**

**`server/soundings/core/config.py`:**

```python
from functools import lru_cache
from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOUNDINGS_", env_file=None)

    database_url: PostgresDsn = "postgresql+asyncpg://soundings:changeme-locally@localhost:5432/soundings"  # type: ignore[assignment]
    log_level: str = "info"
    env: str = "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    import os
    # DATABASE_URL is conventional and overrides SOUNDINGS_DATABASE_URL
    if "DATABASE_URL" in os.environ:
        return Settings(database_url=os.environ["DATABASE_URL"])  # type: ignore[arg-type]
    return Settings()
```

**`server/soundings/db/engine.py`:**

```python
from functools import lru_cache
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from soundings.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        str(settings.database_url),
        pool_size=10,
        max_overflow=5,
        pool_pre_ping=True,
    )
```

**`server/soundings/db/__init__.py`:** empty.

**`server/tests/conftest.py`:**

```python
import os
import pytest


@pytest.fixture(scope="session", autouse=True)
def _set_test_db_env() -> None:
    # Tests assume `make up` is running. CI runs them inside a service container.
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://soundings:changeme-locally@localhost:5432/soundings",
    )
```

**Step 4: Run the test.**

```bash
cd server && uv run pytest tests/test_db_connection.py -v
```

Expect: PASS.

**Step 5: Commit.**

```bash
git add server/soundings/db server/soundings/core server/tests
git commit -m "feat(db): add async engine and integration test against postgis"
```

### Task 10: Add `/healthz` endpoint (TDD)

**Files:**
- Create: `server/soundings/app.py`
- Create: `server/soundings/http/__init__.py`
- Create: `server/soundings/http/health.py`
- Create: `server/tests/test_healthz.py`

**Step 1: Write failing test.**

```python
# server/tests/test_healthz.py
import pytest
from httpx import ASGITransport, AsyncClient

from soundings.app import app

pytestmark = pytest.mark.integration


async def test_healthz_returns_ok_when_db_reachable():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["postgres"] == "ok"
```

**Step 2: Run.** Expect import error.

**Step 3: Implement.**

```python
# server/soundings/http/health.py
from fastapi import APIRouter
from sqlalchemy import text

from soundings.db.engine import get_engine

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict:
    checks: dict[str, str] = {}
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = f"fail: {exc.__class__.__name__}"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}
```

```python
# server/soundings/app.py
from fastapi import FastAPI
from soundings.http.health import router as health_router

app = FastAPI(title="Soundings", version="0.0.1")
app.include_router(health_router)
```

**Step 4: Run.** Expect PASS.

**Step 5: Commit.** `feat(http): add /healthz endpoint`.

---

## Block C — Alembic migrations for all five schemas (Tasks 11–15)

### Task 11: Initialise Alembic

**Files:**
- Create: `server/alembic.ini`
- Create: `server/soundings/db/migrations/env.py`
- Create: `server/soundings/db/migrations/script.py.mako`
- Create: `server/soundings/db/models/__init__.py` — empty for now; collected MetaData lives here

**Steps:**
1. From `server/`: `uv run alembic init -t async soundings/db/migrations` then move `alembic.ini` to `server/alembic.ini`. (Manual edit fine; alembic init can be finicky on Windows.)
2. Edit `alembic.ini`: `script_location = soundings/db/migrations`. Remove the `sqlalchemy.url` line entirely (we read from env).
3. Edit `soundings/db/migrations/env.py`:

```python
import asyncio
from logging.config import fileConfig
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool
from alembic import context

from soundings.core.config import get_settings
from soundings.db.models import metadata  # we'll define this in task 12

config = context.config
config.set_main_option("sqlalchemy.url", str(get_settings().database_url))
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        version_table_schema="public",
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

4. Commit: `chore(db): initialise alembic with async env`.

### Task 12: First migration — `geography` schema

**Files:**
- Create: `server/soundings/db/models/geography.py`
- Modify: `server/soundings/db/models/__init__.py`
- Generate: `server/soundings/db/migrations/versions/0001_geography.py`

**Step 1: Write a model-shape test.**

```python
# server/tests/test_geography_models.py
import pytest
from sqlalchemy import select

from soundings.db.engine import get_engine
from soundings.db.models.geography import Place

pytestmark = pytest.mark.integration


async def test_place_table_exists_with_required_columns():
    engine = get_engine()
    async with engine.connect() as conn:
        # ANY query that names every required column proves the table is migrated correctly
        result = await conn.execute(
            select(Place.id, Place.type, Place.code, Place.name).limit(0)
        )
        # Empty cursor is fine — we only need the SQL to compile against the live schema
        assert result.keys() == ("id", "type", "code", "name")
```

**Step 2: Run.** Expect "no such table" / import error.

**Step 3: Implement models.**

```python
# server/soundings/db/models/__init__.py
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData


class Base(DeclarativeBase):
    metadata = MetaData()


metadata = Base.metadata

# Import models so Alembic's autogenerate sees them
from soundings.db.models import geography  # noqa: E402, F401
```

```python
# server/soundings/db/models/geography.py
from datetime import date, datetime
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from soundings.db.models import Base


class Place(Base):
    __tablename__ = "place"
    __table_args__ = (
        UniqueConstraint("type", "code", "valid_from", name="uq_place_type_code_validfrom"),
        Index("ix_place_geom", "geom", postgresql_using="gist"),
        {"schema": "geography"},
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=True)


class PlaceHierarchy(Base):
    __tablename__ = "place_hierarchy"
    __table_args__ = ({"schema": "geography"},)

    child_id: Mapped[str] = mapped_column(ForeignKey("geography.place.id"), primary_key=True)
    parent_id: Mapped[str] = mapped_column(ForeignKey("geography.place.id"), primary_key=True)


class Postcode(Base):
    __tablename__ = "postcode"
    __table_args__ = ({"schema": "geography"},)

    postcode: Mapped[str] = mapped_column(String(8), primary_key=True)
    lsoa21: Mapped[Optional[str]] = mapped_column(ForeignKey("geography.place.id"), nullable=True)
    msoa21: Mapped[Optional[str]] = mapped_column(ForeignKey("geography.place.id"), nullable=True)
    ltla24: Mapped[Optional[str]] = mapped_column(ForeignKey("geography.place.id"), nullable=True)
    utla24: Mapped[Optional[str]] = mapped_column(ForeignKey("geography.place.id"), nullable=True)
    ward24: Mapped[Optional[str]] = mapped_column(ForeignKey("geography.place.id"), nullable=True)
    westminster_constituency_24: Mapped[Optional[str]] = mapped_column(ForeignKey("geography.place.id"), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(ForeignKey("geography.place.id"), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(ForeignKey("geography.place.id"), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CodeChange(Base):
    __tablename__ = "code_change"
    __table_args__ = ({"schema": "geography"},)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    old_code: Mapped[str] = mapped_column(String(32))
    new_code: Mapped[str] = mapped_column(String(32))
    change_type: Mapped[str] = mapped_column(String(32))
    effective_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

**Step 4: Generate the migration.**

```bash
cd server && uv run alembic revision --autogenerate -m "geography schema"
```

Inspect the generated `versions/0001_*.py`. It should include `op.create_table('place', ..., schema='geography')` and so on. **Manually verify** the indexes and FKs survived autogeneration — sometimes GeoAlchemy2 indexes need a hand-edit.

**Step 5: Apply and run the test.**

```bash
make migrate
cd server && uv run pytest tests/test_geography_models.py -v
```

Expect PASS.

**Step 6: Commit.**

```bash
git add server/soundings/db/models server/soundings/db/migrations
git commit -m "feat(db): geography schema — place, hierarchy, postcode, code_change"
```

### Task 13: Add `catalogue` schema models + migration

Same TDD pattern as Task 12. Models for `Indicator` and `Source` per design §2. New migration `0002_catalogue.py`. Test hits both tables.

**Files:**
- Create: `server/soundings/db/models/catalogue.py`
- Modify: `server/soundings/db/models/__init__.py` — add `from . import catalogue`
- Create: `server/tests/test_catalogue_models.py`
- Generate: `server/soundings/db/migrations/versions/0002_catalogue.py`

**Indicator model fields (from design §2):**
- `key` (PK), `label`, `description`, `unit`, `higher_is`, `source_id` (FK → catalogue.source.id), `available_at` (text array), `refresh_cadence`, `caveats` (jsonb), `related_keys` (text array), `catalogue_version`.

**Source model fields:**
- `id` (PK), `label`, `publisher`, `publisher_url`, `dataset_url`, `licence`, `mode` (enum-ish: 'loader' | 'passthrough'), `refresh_cadence`, `rate_limit` (jsonb).

Use `sqlalchemy.dialects.postgresql.ARRAY(String)`, `JSONB`. Add a `CheckConstraint("mode IN ('loader','passthrough')")` on Source.

Commit: `feat(db): catalogue schema — indicator, source`.

### Task 14: Add `data` schema models + migration

**Files:**
- Create: `server/soundings/db/models/data.py`
- Create: `server/tests/test_data_models.py`
- Generate: `server/soundings/db/migrations/versions/0003_data.py`

Models: `IndicatorValue`, `TrendPoint`, `Organisation`, `OrganisationOperatesIn`, `GrantRecord`, `LoaderRun`. Field shapes as per design §2.

For Phase 0 only `LoaderRun` is read/written (we'll need it for the geography loader). The other models exist as schema but aren't queried in this phase. Still write the full migration now so we don't churn migrations later.

Commit: `feat(db): data schema — indicator values, trends, organisations, grants, loader runs`.

### Task 15: Add `cache` and `corpus` schema models + migrations

**Files:**
- Create: `server/soundings/db/models/cache.py` — `SourceCache` model.
- Create: `server/soundings/db/models/corpus.py` — `QuestionRecord`, `RawRecord` models.
- Generate: `server/soundings/db/migrations/versions/0004_cache_and_corpus.py`.

Tests hit each table with a no-op `select(...).limit(0)` to confirm migration ran cleanly.

For `RawRecord`: this migration also creates a restricted role:

```sql
-- inside the migration, after table creation
CREATE ROLE soundings_sanitiser NOLOGIN;
GRANT SELECT, DELETE ON corpus.raw_record TO soundings_sanitiser;
REVOKE ALL ON corpus.raw_record FROM PUBLIC;
GRANT INSERT ON corpus.raw_record TO soundings;  -- main app can write
```

(Add via `op.execute(...)` so `alembic downgrade` can revoke cleanly.)

Commit: `feat(db): cache + corpus schemas with restricted role on raw_record`.

---

## Block D — Catalogue loader (Tasks 16–20)

### Task 16: Author `catalogue/sources.yaml`

**Files:**
- Create: `catalogue/sources.yaml` (full v1 source list per design §3).

**Content:**

```yaml
# catalogue/sources.yaml — v1 sources, pinned per design 2026-05-05 §3.
# Each entry includes: mode (loader|passthrough), refresh policy, licence,
# publisher metadata for SourceRef construction.

sources:
  - id: ons.geography
    label: ONS Open Geography Portal
    publisher: Office for National Statistics
    publisher_url: https://geoportal.statistics.gov.uk/
    dataset_url: https://geoportal.statistics.gov.uk/
    licence: OGL-UK-3.0
    mode: loader
    refresh_cadence: "0 2 1 */3 *"
    rate_limit: { rps: 4 }

  - id: postcodes.io
    label: postcodes.io
    publisher: postcodes.io
    publisher_url: https://postcodes.io/
    dataset_url: https://api.postcodes.io/
    licence: MIT
    mode: passthrough
    ttl_hours: 720
    rate_limit: { rps: 10 }

  - id: ons.census2021
    label: ONS Census 2021
    publisher: Office for National Statistics
    publisher_url: https://www.ons.gov.uk/census
    dataset_url: https://www.nomisweb.co.uk/
    licence: OGL-UK-3.0
    mode: loader
    refresh_cadence: "0 2 1 1 *"
    rate_limit: { rps: 2 }

  - id: ons.aps
    label: ONS Annual Population Survey
    publisher: Office for National Statistics
    publisher_url: https://www.ons.gov.uk/
    dataset_url: https://www.nomisweb.co.uk/
    licence: OGL-UK-3.0
    mode: passthrough
    ttl_hours: 24
    rate_limit: { rps: 2 }

  - id: mhclg.imd2019
    label: English Indices of Deprivation 2019
    publisher: Ministry of Housing, Communities and Local Government
    publisher_url: https://www.gov.uk/government/statistics/english-indices-of-deprivation-2019
    dataset_url: https://www.gov.uk/government/statistics/english-indices-of-deprivation-2019
    licence: OGL-UK-3.0
    mode: loader
    refresh_cadence: "0 3 1 * *"

  - id: mhclg.live_tables
    label: MHCLG Live Tables
    publisher: Ministry of Housing, Communities and Local Government
    publisher_url: https://www.gov.uk/government/statistical-data-sets
    dataset_url: https://www.gov.uk/government/statistical-data-sets
    licence: OGL-UK-3.0
    mode: loader
    refresh_cadence: "0 4 * * 1"

  - id: dwp.statxplore
    label: DWP Stat-Xplore
    publisher: Department for Work and Pensions
    publisher_url: https://stat-xplore.dwp.gov.uk/
    dataset_url: https://stat-xplore.dwp.gov.uk/webapi/online-help/
    licence: OGL-UK-3.0
    mode: passthrough
    ttl_hours: 24
    rate_limit: { rps: 2 }

  - id: ohid.fingertips
    label: OHID Fingertips
    publisher: Office for Health Improvement and Disparities
    publisher_url: https://fingertips.phe.org.uk/
    dataset_url: https://fingertips.phe.org.uk/api
    licence: OGL-UK-3.0
    mode: passthrough
    ttl_hours: 24
    rate_limit: { rps: 4 }

  - id: dfe.explore
    label: Explore Education Statistics
    publisher: Department for Education
    publisher_url: https://explore-education-statistics.service.gov.uk/
    dataset_url: https://content.explore-education-statistics.service.gov.uk/api/
    licence: OGL-UK-3.0
    mode: passthrough
    ttl_hours: 24
    rate_limit: { rps: 2 }

  - id: police_uk
    label: data.police.uk
    publisher: Home Office
    publisher_url: https://data.police.uk/
    dataset_url: https://data.police.uk/docs/
    licence: OGL-UK-3.0
    mode: passthrough
    ttl_hours: 24
    rate_limit: { rps: 10 }

  - id: charity_commission
    label: Charity Commission Register
    publisher: Charity Commission for England and Wales
    publisher_url: https://register-of-charities.charitycommission.gov.uk/
    dataset_url: https://register-of-charities.charitycommission.gov.uk/register/api
    licence: OGL-UK-3.0
    mode: loader
    refresh_cadence: "0 2 * * *"

  - id: 360giving
    label: 360Giving Datastore
    publisher: 360Giving
    publisher_url: https://www.threesixtygiving.org/
    dataset_url: https://grantnav.threesixtygiving.org/
    licence: CC-BY-4.0
    mode: loader
    refresh_cadence: "0 5 * * 0"

  - id: find_that_charity
    label: Find That Charity
    publisher: Find That Charity
    publisher_url: https://findthatcharity.uk/
    dataset_url: https://findthatcharity.uk/about
    licence: CC-BY-SA-4.0
    mode: passthrough
    ttl_hours: 168
    rate_limit: { rps: 4 }
```

Commit: `feat(catalogue): add sources.yaml with v1 source list`.

### Task 17: Pydantic models for catalogue entries

**Files:**
- Create: `server/soundings/catalogue/models.py`
- Create: `server/tests/test_catalogue_yaml_load.py`

**Step 1: Failing test.**

```python
# server/tests/test_catalogue_yaml_load.py
from pathlib import Path
from soundings.catalogue.models import load_sources_yaml, load_indicators_yaml


def test_sources_yaml_loads_and_validates():
    sources = load_sources_yaml(Path("../catalogue/sources.yaml"))
    ids = {s.id for s in sources}
    assert "ons.geography" in ids
    assert "postcodes.io" in ids
    # Mode constraint
    for s in sources:
        assert s.mode in ("loader", "passthrough")
        if s.mode == "passthrough":
            assert s.ttl_hours is not None and s.ttl_hours > 0
        if s.mode == "loader":
            assert s.refresh_cadence is not None


def test_indicators_yaml_loads_and_references_known_sources():
    indicators = load_indicators_yaml(Path("../catalogue/indicators.yaml"))
    sources = load_sources_yaml(Path("../catalogue/sources.yaml"))
    source_ids = {s.id for s in sources}
    for ind in indicators:
        assert ind.source_id in source_ids, f"{ind.key} references unknown {ind.source_id}"
```

**Step 3: Implement.**

```python
# server/soundings/catalogue/models.py
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class SourceModel(BaseModel):
    id: str
    label: str
    publisher: str
    publisher_url: Optional[str] = None
    dataset_url: Optional[str] = None
    licence: str
    mode: Literal["loader", "passthrough"]
    refresh_cadence: Optional[str] = None
    ttl_hours: Optional[int] = None
    rate_limit: dict = Field(default_factory=dict)

    @field_validator("ttl_hours")
    @classmethod
    def passthrough_needs_ttl(cls, v, info):
        # Cross-field validation handled in test for now
        return v


class IndicatorModel(BaseModel):
    key: str
    label: str
    description: Optional[str] = None
    unit: str
    higher_is: Optional[Literal["better", "worse", "neither"]] = None
    source_id: str
    available_at: list[str]
    refresh_cadence: Optional[str] = None
    caveats: list[str] = Field(default_factory=list)
    related_keys: list[str] = Field(default_factory=list)


def load_sources_yaml(path: Path) -> list[SourceModel]:
    raw = yaml.safe_load(path.read_text())
    return [SourceModel(**s) for s in raw["sources"]]


def load_indicators_yaml(path: Path) -> list[IndicatorModel]:
    raw = yaml.safe_load(path.read_text())
    # Top-level shape of indicators.yaml per spec §5 — adapt if file is wrapped
    items = raw.get("indicators", raw) if isinstance(raw, dict) else raw
    return [IndicatorModel(**i) for i in items]
```

**Step 4:** Run test.

```bash
cd server && uv run pytest tests/test_catalogue_yaml_load.py -v
```

If `indicators.yaml` shape doesn't match, adjust `load_indicators_yaml` — read the actual file structure from `catalogue/indicators.yaml` and conform. Iterate until tests pass.

**Step 5:** Commit: `feat(catalogue): pydantic loaders for indicators.yaml and sources.yaml`.

### Task 18: Catalogue → Postgres upsert function

**Files:**
- Create: `server/soundings/catalogue/loader.py`
- Create: `server/tests/test_catalogue_loader.py`

The function `load_catalogue_into_db(engine, sources_path, indicators_path) -> None`:
1. Computes a `catalogue_version` = SHA-256 of the indicators yaml file contents.
2. Begins transaction.
3. Upserts sources (`INSERT … ON CONFLICT (id) DO UPDATE`).
4. Upserts indicators with the computed catalogue_version stamped on each row.
5. Commits.

Test: integration test that runs the loader twice and asserts row counts are stable (idempotent) and `catalogue_version` is consistent.

Commit: `feat(catalogue): idempotent loader that upserts sources + indicators with version stamp`.

### Task 19: Wire catalogue load into FastAPI startup

**Files:**
- Modify: `server/soundings/app.py`

Add a startup event (FastAPI 0.115+ uses `lifespan`):

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pathlib import Path

from soundings.http.health import router as health_router
from soundings.catalogue.loader import load_catalogue_into_db
from soundings.db.engine import get_engine


CATALOGUE_DIR = Path(__file__).resolve().parent.parent.parent / "catalogue"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await load_catalogue_into_db(
        get_engine(),
        sources_path=CATALOGUE_DIR / "sources.yaml",
        indicators_path=CATALOGUE_DIR / "indicators.yaml",
    )
    yield


app = FastAPI(title="Soundings", version="0.0.1", lifespan=lifespan)
app.include_router(health_router)
```

Test (integration): start the app via TestClient → query `catalogue.source` → assert row count > 0.

Commit: `feat(app): load catalogue into Postgres at startup`.

### Task 20: Make `/healthz` reflect catalogue load status

**Files:**
- Modify: `server/soundings/http/health.py`
- Modify: `server/tests/test_healthz.py`

Add a `catalogue_loaded` check. Simplest approach: query `SELECT count(*) FROM catalogue.source` and require > 0.

Update test to assert `body["checks"]["catalogue"] == "ok"`.

Commit: `feat(http): /healthz checks catalogue is loaded`.

---

## Block E — Geography seed (Tasks 21–30)

### Task 21: Source list — pin the ONS Open Geography Portal endpoints we'll consume

**Files:**
- Create: `docs/adr/0001-geography-data-sources.md`

Document the exact Open Geography Portal (OGP) and Code History Database endpoints to be hit. This locks decisions before the loader code lands. Concretely identify:

- LSOA 2021 boundaries (BUC — Ultra Generalised Clipped) — feature service URL.
- MSOA 2021 boundaries (BUC).
- LTLA 2024 boundaries (BUC).
- UTLA 2024 boundaries (BUC).
- Region 2024 boundaries.
- Country 2024 boundaries.
- Westminster Constituency 2024 boundaries.
- Ward 2024 boundaries.
- LSOA → MSOA → LTLA → ICB → Region lookup (current).
- Westminster constituency → LTLA lookup.
- Ward → LTLA → UTLA lookup.
- Code History Database (CHD) full-area-changes table.

For each, capture the OGP service URL. (These move occasionally — recording them in an ADR means a stale URL becomes a single-file fix, not a hunt through code.)

Commit: `docs: ADR-0001 geography data sources and OGP endpoints`.

### Task 22: `ons.geography` loader — places (codes + names, no geometries)

**Files:**
- Create: `server/soundings/adapters/__init__.py`
- Create: `server/soundings/adapters/base.py` — `LoaderAdapter` ABC with `load(run_id) -> LoaderResult`.
- Create: `server/soundings/adapters/ons_geography/__init__.py`
- Create: `server/soundings/adapters/ons_geography/places_loader.py`
- Create: `server/tests/cassettes/ons_geography/places_lsoa_sample.yaml`
- Create: `server/tests/test_ons_geography_places.py`

**Pattern:** Loader fetches each level's lookup, normalises to `Place(id="<type>:<code>", type, code, name, valid_from, valid_to=None)`, upserts to `geography.place`. No geometries here yet.

**Test approach:** Use `pytest-vcr` to record a single OGP query against ~5 LSOAs (filtered by query parameter) and assert the loader produces matching `Place` rows. Cassette is committed.

Step-by-step:
1. Failing test that creates an in-memory loader, runs against the recorded cassette, and asserts 5 LSOA rows in `geography.place`.
2. Implement `LoaderAdapter` ABC: `mode = "loader"`, `source_id`, `async def load(run_id)`.
3. Implement `OnsGeographyPlacesLoader.load`: paginate the OGP feature service, batch-upsert.
4. Run test: PASS.
5. Commit: `feat(adapters): ons.geography places loader (codes + names)`.

### Task 23: `ons.geography` loader — `place_hierarchy` from lookup tables

**Files:**
- Create: `server/soundings/adapters/ons_geography/hierarchy_loader.py`
- Create: `server/tests/test_ons_geography_hierarchy.py`
- Create: `server/tests/cassettes/ons_geography/lookup_lsoa_msoa_ltla.yaml`

Reads the LSOA→MSOA→LTLA lookup table from OGP, expands into `(child_id, parent_id)` rows for every transitive parent so a single SELECT can answer "what contains this LSOA". Upserts into `geography.place_hierarchy`.

Test: load a known LSOA, query `SELECT parent_id FROM place_hierarchy WHERE child_id = 'lsoa21:E01001234'`, assert MSOA, LTLA, UTLA, region, country IDs are present.

Commit: `feat(adapters): ons.geography hierarchy loader (transitive containment)`.

### Task 24: `ons.geography` loader — Westminster constituencies

Same TDD pattern. Add `wcons24:` IDs and the constituency → LTLA lookup into `place_hierarchy`.

Commit: `feat(adapters): ons.geography Westminster constituency 2024 loader`.

### Task 25: `ons.geography` loader — wards

Same TDD pattern. Add `ward24:` IDs and the ward → LTLA → UTLA lookup.

Commit: `feat(adapters): ons.geography ward 2024 loader`.

### Task 26: `ons.geography` loader — boundary geometries (BUC simplified)

**Files:**
- Create: `server/soundings/adapters/ons_geography/geometries_loader.py`
- Create: `server/tests/test_ons_geography_geometries.py`
- Create: `server/tests/cassettes/ons_geography/geom_ltla_E07000223.yaml`

**Step 1:** Failing test — load a single LTLA's BUC geometry, assert `geom IS NOT NULL` and `ST_IsValid(geom)`.

**Step 3:** Implement.
- For each layer (LSOA21, MSOA21, LTLA24, UTLA24, Region, Country, WCON24, Ward24): fetch GeoJSON FeatureCollection, paginate (OGP returns ~1000 per page).
- Convert each Feature's geometry to `MultiPolygon` (some come as Polygon — wrap them) at SRID 4326.
- Update existing `place` rows: `UPDATE geography.place SET geom = ST_GeomFromGeoJSON(:geojson) WHERE id = :id`.
- Use `WKBElement` from `geoalchemy2` if you'd rather go via shapely.

**Step 4:** Run test, expect PASS.

**Step 5:** Commit: `feat(adapters): ons.geography BUC simplified boundary loader`.

### Task 27: `ons.geography` loader — code change history

**Files:**
- Create: `server/soundings/adapters/ons_geography/code_change_loader.py`
- Create: `server/tests/test_ons_geography_code_change.py`

Loads ONS Code History Database area-changes table into `geography.code_change`.

Commit: `feat(adapters): ons.geography code history database loader`.

### Task 28: `postcodes.io` adapter scaffolding (passthrough)

**Files:**
- Create: `server/soundings/adapters/passthrough_base.py` — `PassthroughAdapter` ABC per design §3.
- Create: `server/soundings/cache/__init__.py`
- Create: `server/soundings/cache/source_cache.py`
- Create: `server/tests/test_source_cache.py`

`PassthroughAdapter` ABC encapsulates: cache lookup → upstream call (rate-limited, retried) → cache write → SourceRef construction. Subclasses implement `_call_upstream` and `_materialise`.

Source cache helpers: `get(source_id, key)`, `put(source_id, key, payload, ttl)`, `delete_expired()`.

Failing test → integration test for the cache: put then get within TTL → returns payload; put then advance time past TTL → returns None; delete_expired removes stale rows.

Commit: `feat(adapters): passthrough adapter base + source_cache helpers`.

### Task 29: `postcodes.io` adapter — single postcode lookup

**Files:**
- Create: `server/soundings/adapters/postcodes_io/__init__.py`
- Create: `server/soundings/adapters/postcodes_io/adapter.py`
- Create: `server/tests/cassettes/postcodes_io/ts18_1ab.yaml`
- Create: `server/tests/test_postcodes_io.py`

Adapter method: `async def lookup(postcode: str) -> PostcodeResult | None`. Returns canonical place IDs for LSOA21, MSOA21, LTLA24, UTLA24, Region, Country, Westminster constituency, Ward (postcodes.io exposes all of these — note: they use older code editions sometimes; map to current via `code_change` table where needed).

Test:
1. Cassette of `GET https://api.postcodes.io/postcodes/TS181AB`.
2. Call `adapter.lookup("TS18 1AB")` → assert all eight `*_id` fields populated, all reference `geography.place` rows that exist.

Implementation note: postcodes.io returns mixed code editions. For each returned code, attempt `place.id = "<type>:<code>"` directly; if not found, look up `code_change` for a current successor; if still not found, return null for that level (and log, not error).

Commit: `feat(adapters): postcodes.io single-postcode lookup with code-change fallback`.

### Task 30: `postcodes.io` adapter — write into `geography.postcode` cache table

Adapter exposes a higher-level method `async def upsert_postcode(postcode: str) -> Postcode` that:
1. Calls `lookup(postcode)`.
2. Upserts the result into `geography.postcode` with `retrieved_at = now()`.
3. Returns the row.

Test: integration test asserts a fresh row appears with correct `lsoa21`, `ltla24`, etc.

Commit: `feat(adapters): postcodes.io upsert into geography.postcode cache`.

---

## Block F — GeographyService (Tasks 31–35)

### Task 31: `GeographyService.find_place_by_postcode`

**Files:**
- Create: `server/soundings/geography/__init__.py`
- Create: `server/soundings/geography/service.py`
- Create: `server/tests/test_geography_service.py`

The service is the orchestrator-facing API for everything spatial. Method:

```python
async def find_place_by_postcode(self, postcode: str) -> dict[str, Place] | None:
    """Returns dict keyed by place type → Place, for all containing levels."""
```

Implementation: check `geography.postcode` for a fresh (< 30 days) row. If miss/stale, call `postcodes_io_adapter.upsert_postcode`. Then load each `*_id` via a single SQL JOIN.

Test (integration, with cassette): `find_place_by_postcode("TS18 1AB")` → returns dict with at least `lsoa21`, `msoa21`, `ltla24`, `utla24`, `region`, `country`, `westminster_constituency_24`, `ward24`.

Commit: `feat(geography): GeographyService.find_place_by_postcode`.

### Task 32: `GeographyService.find_place_by_name` (fuzzy)

Method:

```python
async def find_place_by_name(
    self, query: str, geography_types: list[str] | None = None, limit: int = 5
) -> list[PlaceMatch]:
```

Uses pg_trgm: `ORDER BY similarity(name, :query) DESC`. `PlaceMatch` includes confidence (the similarity score, normalised 0–1).

Test: search "stockton" → top result is `ltla24:E07000223 Stockton-on-Tees`.

Commit: `feat(geography): fuzzy place-name search via pg_trgm`.

### Task 33: `GeographyService.find_containing_places` via hierarchy

Method:

```python
async def find_containing_places(self, place_id: str) -> list[Place]:
```

Single SELECT against `place_hierarchy` returning all parents.

Test: input `lsoa21:<known>` → returns list including its MSOA, LTLA, UTLA, region, country.

Commit: `feat(geography): find_containing_places via place_hierarchy`.

### Task 34: `GeographyService.find_containing_places_by_geom` via PostGIS

Variant that uses `ST_Within` against `place.geom`. Useful for ad-hoc points (e.g. "what LTLA contains this lat/lng?") and as a sanity check on the hierarchy data.

Method:

```python
async def find_containing_places_by_point(
    self, lat: float, lng: float, types: list[str] | None = None
) -> list[Place]:
```

Test: known coordinates within Stockton → returns the same LTLA via geometry as the hierarchy returns.

Commit: `feat(geography): point-in-polygon containing-place lookup via PostGIS`.

### Task 35: End-to-end integration test — postcode → all geographies

**Files:**
- Create: `server/tests/test_phase_0_e2e.py`

The Phase 0 acceptance test. Runs against a fresh `make up` + `make seed-light` stack:

```python
import pytest
from soundings.geography.service import GeographyService

pytestmark = pytest.mark.integration


async def test_postcode_resolves_to_all_geographies():
    svc = GeographyService()
    result = await svc.find_place_by_postcode("TS18 1AB")  # central Stockton

    assert result is not None
    assert "lsoa21" in result
    assert "msoa21" in result
    assert "ltla24" in result
    assert result["ltla24"].name == "Stockton-on-Tees"
    assert result["utla24"].name == "Stockton-on-Tees"  # unitary so same
    assert result["region"].name == "North East"
    assert result["country"].name == "England"
    assert result["westminster_constituency_24"] is not None
    assert result["ward24"] is not None


async def test_hierarchy_and_geometry_agree():
    svc = GeographyService()
    via_hierarchy = await svc.find_containing_places("lsoa21:E01012018")  # a Stockton LSOA
    via_geom = await svc.find_containing_places_by_point(54.5675, -1.3177)

    hier_ltla = next(p for p in via_hierarchy if p.type == "ltla24")
    geom_ltla = next(p for p in via_geom if p.type == "ltla24")
    assert hier_ltla.id == geom_ltla.id
```

Commit: `test: phase 0 e2e — postcode resolves to full geography tree`.

---

## Block G — Tooling, CI, smoke deploy, tag (Tasks 36–40)

### Task 36: `make seed` and `make seed-light` implementations

**Files:**
- Create: `server/soundings/seed/__init__.py`
- Create: `server/soundings/seed/run.py`

`run.py` is a CLI module: `python -m soundings.seed.run --full | --light`.

`--full` runs all `ons.geography` loaders end-to-end (places, hierarchy, geometries, code changes) for every supported level.

`--light` restricts to a single LTLA (e.g. Stockton `E07000223`) and its descendant LSOAs/MSOAs/wards. Add a `--ltla` arg to override.

`run.py` writes a row to `data.loader_run` per source, with status. On exception: `status='failed'`, the exception message into `notes`, raise.

Manual step: `make up && make migrate && make seed-light` should complete in < 5 min and leave the DB ready for `test_phase_0_e2e.py`.

Commit: `feat(seed): make seed and make seed-light run ons.geography loaders`.

### Task 37: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

```yaml
name: ci

on:
  pull_request:
  push:
    branches: [main]

jobs:
  lint-type:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          version: "0.5.10"
      - run: cd server && uv sync --frozen
      - run: cd server && uv run ruff check .
      - run: cd server && uv run ruff format --check .
      - run: cd server && uv run mypy soundings

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgis/postgis:16-3.4
        env:
          POSTGRES_DB: soundings
          POSTGRES_USER: soundings
          POSTGRES_PASSWORD: changeme-locally
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U soundings"
          --health-interval 5s --health-timeout 3s --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with: { version: "0.5.10" }
      - run: cd server && uv sync --frozen
      - run: |
          PGPASSWORD=changeme-locally psql -h localhost -U soundings -d soundings -f infra/initdb/00-extensions.sql
          PGPASSWORD=changeme-locally psql -h localhost -U soundings -d soundings -f infra/initdb/01-schemas.sql
      - run: cd server && DATABASE_URL=postgresql+asyncpg://soundings:changeme-locally@localhost:5432/soundings uv run alembic upgrade head
      - run: cd server && DATABASE_URL=postgresql+asyncpg://soundings:changeme-locally@localhost:5432/soundings uv run pytest -m "not live"

  live-tests:
    if: github.event_name == 'schedule'
    runs-on: ubuntu-latest
    services: { postgres: { image: postgis/postgis:16-3.4, ... } }   # same as above
    steps:
      - uses: actions/checkout@v4
      - run: cd server && uv run pytest -m live
```

(Plus a separate workflow file `nightly.yml` with `on: schedule: - cron: '0 4 * * *'` triggering `live-tests`.)

Commit: `ci: lint, type, integration tests on PR + nightly live-API workflow`.

### Task 38: Pre-commit hooks

**Files:**
- Create: `.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ["--maxkb=2048"]
```

Run `pre-commit install` once on each dev machine.

Commit: `chore: pre-commit hooks for ruff, formatting, large-file guard`.

### Task 39: Smoke deploy to the Mac mini

**Goal:** Prove the existing Cloudflare Tunnel can route to the stack. No real traffic yet.

**Steps:**
1. On the Mac mini, `git clone <repo>` and `cd soundings`.
2. Generate a dev `.env` with a strong `POSTGRES_PASSWORD`.
3. Add a Caddy config for the `infra/Caddyfile`:

```caddy
:80 {
    handle /v1/* { reverse_proxy server:8000 }
    handle       { respond "soundings phase 0 — UI not yet wired" 200 }
}
```

4. Add `caddy` service to `docker-compose.yml`:

```yaml
caddy:
  image: caddy:2
  volumes:
    - ./infra/Caddyfile:/etc/caddy/Caddyfile:ro
    - caddy_data:/data
  ports: ["127.0.0.1:8088:80"]
volumes:
  caddy_data:
```

5. Add an additive ingress rule to `~/.cloudflared/config.yml`:

```yaml
ingress:
  - hostname: soundings.<your-domain>
    service: http://localhost:8088
  # …existing rules below, unchanged…
```

6. `sudo launchctl kickstart -k system/com.cloudflare.cloudflared` (or whatever the existing process manager is).
7. Verify externally: `curl -fsS https://soundings.<your-domain>/healthz` returns the JSON.

**Caveat:** before applying this, confirm the hostname doesn't collide with anything already on the tunnel.

Commit (config-only): `infra: smoke deploy — caddy + cloudflare tunnel ingress for soundings.*`.

### Task 40: Tag `v0.1.0-phase-0`

**Steps:**
1. Confirm green: `make lint && make type && make test && make test-integration`.
2. Confirm `make up && make migrate && make seed-light && cd server && uv run pytest -m integration` passes locally.
3. Confirm the Mac mini smoke deploy is up.
4. Update `STATE.md` and `PLAN.md` with phase 0 done + summary of what's live.
5. Tag and push:

```bash
git tag -a v0.1.0-phase-0 -m "phase 0: repo, schema, geography spine end-to-end"
git push origin v0.1.0-phase-0
```

Commit (for STATE/PLAN updates): `docs: phase 0 complete — geography spine live`.

---

## Done criteria for Phase 0

All of these green simultaneously:

- [ ] Public GitHub repo exists with three licence files at root.
- [ ] `make up && make migrate` brings the stack up and applies all four migrations.
- [ ] `make seed-light` completes in < 5 minutes against a fresh DB.
- [ ] `cd server && uv run pytest -m "not live"` passes.
- [ ] `cd server && uv run pytest -m integration` passes against the running stack.
- [ ] `tests/test_phase_0_e2e.py` resolves `TS18 1AB` to all eight geography levels with names that match expectations.
- [ ] `tests/test_phase_0_e2e.py` confirms hierarchy lookup and PostGIS point-in-polygon agree.
- [ ] CI on `main` is green.
- [ ] Mac mini smoke deploy responds to `https://soundings.<domain>/healthz` with `{"status": "ok"}`.
- [ ] Tag `v0.1.0-phase-0` pushed.

---

## What's next (preview, not in this plan)

**Phase 1** — adapters for postcodes.io (already done in Phase 0 as part of the spine), ONS Census 2021 via Nomis, and MHCLG IMD; plus the first three MCP tools (`find_place`, `get_place_profile`, `get_indicators`) over the new HTTP and MCP transports. To be planned as `docs/plans/<date>-soundings-v1-phase-1-plan.md` once Phase 0 is shipped.

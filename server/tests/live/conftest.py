"""Live test setup.

The nightly CI workflow runs migrations but not the catalogue loader; the
FastAPI lifespan that normally seeds `catalogue.{source,indicator}` doesn't
fire when tests instantiate adapters directly. Without those rows, FK
violations from `data.indicator_value` break every live insert.

Idempotent — re-running for each live test is cheap and self-contained.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

from soundings.catalogue.loader import load_catalogue_into_db
from soundings.db.engine import get_engine

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SOURCES_YAML = REPO_ROOT / "catalogue" / "sources.yaml"
INDICATORS_YAML = REPO_ROOT / "catalogue" / "indicators.yaml"


@pytest_asyncio.fixture(autouse=True)
async def _load_catalogue() -> AsyncIterator[None]:
    engine = get_engine()
    await load_catalogue_into_db(
        engine,
        sources_path=SOURCES_YAML,
        indicators_path=INDICATORS_YAML,
    )
    yield

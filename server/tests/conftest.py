import os
from collections.abc import AsyncIterator

import pytest_asyncio


def pytest_configure(config: object) -> None:
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings",
    )


@pytest_asyncio.fixture(autouse=True)
async def _reset_engine_per_test() -> AsyncIterator[None]:
    """Each pytest-asyncio test runs in its own event loop; the cached
    AsyncEngine binds to the loop it was created on, so we dispose and clear
    the cache after every test to keep the next test's loop happy."""
    yield
    from soundings.db.engine import get_engine

    engine = get_engine.cache_info().currsize and get_engine() or None
    if engine is not None:
        await engine.dispose()
    get_engine.cache_clear()

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

# Tests truncate `geography.place`, `data.organisation`, and other tables
# as cleanup. The default is a SEPARATE database name so a stray pytest
# run can't destroy seeded dev state. Override `DATABASE_URL` to point at
# whatever DB you want; we refuse to run against the dev DB (`/soundings`).
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test"
)
DEV_DATABASE_NAME = "/soundings"


def pytest_configure(config: object) -> None:
    os.environ.setdefault("DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    db_url = os.environ["DATABASE_URL"]
    if db_url.rstrip("/").endswith(DEV_DATABASE_NAME):
        raise pytest.UsageError(
            f"Refusing to run pytest against the dev database "
            f"(DATABASE_URL ends with '{DEV_DATABASE_NAME}'). Tests wipe "
            f"geography + organisation tables as cleanup, which would "
            f"destroy seeded dev state. "
            f"Run `make test-db-create` to bootstrap a separate test DB, "
            f"or set DATABASE_URL to a DB whose name doesn't match the dev DB."
        )


@pytest_asyncio.fixture(autouse=True)
async def _reset_engine_per_test() -> AsyncIterator[None]:
    """Each pytest-asyncio test runs in its own event loop; the cached
    AsyncEngine binds to the loop it was created on, so we dispose and clear
    the cache after every test to keep the next test's loop happy."""
    yield
    from soundings.db.engine import get_engine

    engine = (get_engine.cache_info().currsize and get_engine()) or None
    if engine is not None:
        await engine.dispose()
    get_engine.cache_clear()

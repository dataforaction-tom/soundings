import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from soundings.app import app
from soundings.db.engine import get_engine
from soundings.db.models.catalogue import Source

pytestmark = pytest.mark.integration


async def test_lifespan_loads_catalogue_into_postgres() -> None:
    # Start with an empty catalogue. Dependent caches and loader_run rows
    # reference catalogue.source via FK and need to clear first.
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.loader_run"))
        await conn.execute(text("DELETE FROM catalogue.indicator"))
        await conn.execute(text("DELETE FROM catalogue.source"))

    # The lifespan should populate it on startup.
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test"):
            pass

    async with engine.connect() as conn:
        n_sources = (await conn.execute(select(func.count(Source.id)))).scalar_one()

    assert n_sources > 0

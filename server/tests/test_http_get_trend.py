"""HTTP route tests for POST /v1/tools/get_trend."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from soundings.app import app
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_trend_point() -> AsyncIterator[None]:
    yield
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))


async def _seed_stockton_population_trend() -> None:
    """Three trend points + the source row + the place row. Uses the real
    population.total indicator so the existing ons.mid_year_estimates
    source already registered in app.py picks it up."""
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:E06000004', 'ltla24', 'E06000004', 'Stockton-on-Tees')"
            )
        )
        for period, value in [("2022", 195000.0), ("2023", 196500.0), ("2024", 198000.0)]:
            await conn.execute(
                text(
                    "INSERT INTO data.trend_point "
                    "(place_id, indicator_key, period, value, revised, "
                    "source_id, retrieved_at) "
                    "VALUES ('ltla24:E06000004', 'population.total', :p, :v, "
                    "false, 'ons.mid_year_estimates', :ret)"
                ),
                {"p": period, "v": value, "ret": now},
            )


async def test_post_get_trend_returns_ordered_points() -> None:
    await _seed_stockton_population_trend()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/v1/tools/get_trend",
                json={
                    "place_id": "ltla24:E06000004",
                    "indicator": "population.total",
                },
            )

    assert response.status_code == 200, response.text
    body = response.json()
    trend = body["trend"]
    assert trend is not None
    assert [p["period"] for p in trend["points"]] == ["2022", "2023", "2024"]
    assert trend["points"][-1]["value"] == 198000.0
    assert trend["source"]["source_id"] == "ons.mid_year_estimates"


async def test_list_tools_advertises_get_trend() -> None:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/v1/tools")
    assert response.status_code == 200
    names = [t["name"] for t in response.json()["tools"]]
    assert "get_trend" in names

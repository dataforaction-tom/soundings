import pytest
from httpx import ASGITransport, AsyncClient

from soundings.app import app

pytestmark = pytest.mark.integration


async def test_get_v1_sources_returns_all_phase_1_sources() -> None:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/v1/sources")
    assert response.status_code == 200
    body = response.json()
    ids = {s["id"] for s in body["sources"]}
    assert "ons.mid_year_estimates" in ids
    assert "ons.census2021" in ids
    assert "mhclg.imd2025" in ids
    # last_finished_at is exposed even if empty.
    assert all("last_finished_at" in s for s in body["sources"])


async def test_get_v1_catalogue_indicators_returns_real_indicators() -> None:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/v1/catalogue/indicators")
    assert response.status_code == 200
    body = response.json()
    assert body["catalogue_version"] is not None
    keys = {ind["key"] for ind in body["indicators"]}
    assert "population.total" in keys
    assert "deprivation.imd.score" in keys

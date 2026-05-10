import pytest
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from soundings.app import app
from soundings.db.engine import get_engine
from soundings.orchestration.errors import (
    GeographyNotFoundError,
    IndicatorNotAvailableAtLevelError,
)

pytestmark = pytest.mark.integration


# Register a debug route that raises each error type so we can verify the
# envelope without needing real data.
_debug = APIRouter(prefix="/v1/_debug")


@_debug.post("/raise/geography_not_found")
async def raise_geo() -> None:
    raise GeographyNotFoundError("ltla24:E99999999")


@_debug.post("/raise/indicator_not_available_at_level")
async def raise_level() -> None:
    raise IndicatorNotAvailableAtLevelError(
        "population.households.lone_parent_share",
        "country:E92000001",
        ["lsoa21", "msoa21", "ltla24"],
    )


@_debug.post("/raise/internal")
async def raise_internal() -> None:
    raise RuntimeError("boom")


app.include_router(_debug)


async def test_geography_not_found_returns_404_envelope() -> None:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as ac:
            response = await ac.post("/v1/_debug/raise/geography_not_found")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "GEOGRAPHY_NOT_FOUND"
    assert "ltla24:E99999999" in body["error"]["message"]


async def test_indicator_not_available_at_level_returns_422_envelope() -> None:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as ac:
            response = await ac.post("/v1/_debug/raise/indicator_not_available_at_level")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INDICATOR_NOT_AVAILABLE_AT_LEVEL"
    assert body["error"]["details"]["place_id"] == "country:E92000001"


async def test_internal_errors_return_500_envelope() -> None:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as ac:
            response = await ac.post("/v1/_debug/raise/internal")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL"

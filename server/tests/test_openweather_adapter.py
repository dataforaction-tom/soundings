"""Tests for the OpenWeather air-pollution adapter.

The response parsing, key handling, and indicator->component mapping are
pure units. The centroid lookup + cache + SourceRef path is exercised by
one integration test against the PostGIS test DB with a mocked client.
"""

import httpx
import pytest
from sqlalchemy import text

from soundings.adapters.openweather.adapter import (
    INDICATOR_COMPONENTS,
    METHODOLOGY_CAVEAT,
    OpenWeatherAdapter,
)
from soundings.adapters.openweather.client import OpenWeatherAirClient, _parse_components
from soundings.db.engine import get_engine

# --- pure units (no DB / no network) -------------------------------------

_OWM_PAYLOAD = {
    "coord": {"lon": -1.23, "lat": 54.57},
    "list": [
        {
            "main": {"aqi": 2},
            "components": {
                "co": 230.3,
                "no": 0.1,
                "no2": 8.9,
                "o3": 45.2,
                "so2": 2.3,
                "pm2_5": 6.5,
                "pm10": 9.2,
                "nh3": 0.9,
            },
            "dt": 1_700_000_000,
        }
    ],
}


def test_parse_components_extracts_numeric_pollutants() -> None:
    comps = _parse_components(_OWM_PAYLOAD)
    assert comps is not None
    assert comps["no2"] == 8.9
    assert comps["pm2_5"] == 6.5
    assert comps["o3"] == 45.2


def test_parse_components_handles_empty_or_malformed() -> None:
    assert _parse_components({"list": []}) is None
    assert _parse_components({}) is None
    assert _parse_components("nope") is None
    assert _parse_components({"list": [{}]}) is None


def test_indicator_components_covers_all_five_air_indicators() -> None:
    assert INDICATOR_COMPONENTS == {
        "environment.air_quality.pm25": "pm2_5",
        "environment.air_quality.pm10": "pm10",
        "environment.air_quality.no2": "no2",
        "environment.air_quality.o3": "o3",
        "environment.air_quality.so2": "so2",
    }


async def test_client_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    client = OpenWeatherAirClient()
    with pytest.raises(RuntimeError, match="OPENWEATHER_API_KEY is not set"):
        await client.get_components(54.57, -1.23)


async def test_client_get_components_over_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "air_pollution" in str(request.url)
        return httpx.Response(200, json=_OWM_PAYLOAD)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = OpenWeatherAirClient(http_client=http_client, api_key="test-key")
        comps = await client.get_components(54.57, -1.23)
    assert comps is not None
    assert comps["no2"] == 8.9


# --- integration: centroid + cache + SourceRef ---------------------------


class _FakeOpenWeatherAirClient(OpenWeatherAirClient):
    def __init__(self, components: dict[str, float] | None) -> None:
        self._components = components

    async def get_components(self, lat: float, lng: float) -> dict[str, float] | None:
        del lat, lng
        return self._components


async def _seed_place(place_id: str = "ltla24:E06000004") -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name, geom) "
                "VALUES (:id, 'ltla24', 'E06000004', 'Stockton-on-Tees', "
                "ST_Multi(ST_GeomFromText("
                "'POLYGON((-1.34 54.55, -1.30 54.55, -1.30 54.59, -1.34 54.59, -1.34 54.55))',"
                " 4326)))"
            ),
            {"id": place_id},
        )
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, publisher_url, "
                "dataset_url, licence, mode, rate_limit) VALUES "
                "('openweather', 'OpenWeather Air Pollution', 'OpenWeather', "
                "'https://openweathermap.org/', 'https://openweathermap.org/api/air-pollution', "
                "'CC-BY-SA-4.0', 'passthrough', '{}'::jsonb) ON CONFLICT (id) DO NOTHING"
            )
        )


@pytest.mark.integration
async def test_fetch_indicator_returns_component_value_with_caveat() -> None:
    await _seed_place()
    fake = _FakeOpenWeatherAirClient({"no2": 8.9, "pm2_5": 6.5})
    adapter = OpenWeatherAdapter(get_engine(), owm_client=fake)

    iv = await adapter.fetch_indicator(
        "environment.air_quality.no2", "ltla24:E06000004", period=None
    )
    assert iv is not None
    assert iv.value == 8.9
    assert iv.unit == "µg/m³"
    assert iv.confidence == "modelled"
    assert iv.source.source_id == "openweather"
    assert iv.caveats == [METHODOLOGY_CAVEAT]


@pytest.mark.integration
async def test_fetch_indicator_unknown_indicator_returns_none() -> None:
    await _seed_place()
    adapter = OpenWeatherAdapter(get_engine(), owm_client=_FakeOpenWeatherAirClient({"no2": 8.9}))
    iv = await adapter.fetch_indicator("population.total", "ltla24:E06000004", period=None)
    assert iv is None

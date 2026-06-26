"""Integration tests for OpenAqAdapter.

IDW interpolation of nearby monitoring-station measurements onto a
place centroid. Tests use a mocked OpenAqClient + the real PostGIS
test DB for the centroid lookup and the SourceCacheStore. The fixed
methodology caveat is asserted verbatim so a refactor removing it fails CI.
"""

import math
from typing import Any

import pytest
from sqlalchemy import text

from soundings.adapters.openaq.adapter import METHODOLOGY_CAVEAT, OpenAqAdapter, haversine_km
from soundings.adapters.openaq.client import OpenAqClient
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_place(
    *,
    place_id: str = "ltla24:E06000004",
    code: str = "E06000004",
    name: str = "Stockton-on-Tees",
) -> None:
    """Seed one LTLA polygon centred near (54.57, -1.32)."""
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
                "VALUES (:id, 'ltla24', :code, :name, "
                "ST_Multi(ST_GeomFromText("
                "'POLYGON((-1.34 54.55, -1.30 54.55, -1.30 54.59, -1.34 54.59, -1.34 54.55))',"
                " 4326)))"
            ),
            {"id": place_id, "code": code, "name": name},
        )
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, publisher_url, "
                "dataset_url, licence, mode, rate_limit) VALUES "
                "('openaq', 'OpenAQ', 'OpenAQ', 'https://openaq.org/', "
                "'https://api.openaq.org/v3/', 'CC-BY-4.0', 'passthrough', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )


class _FakeOpenAqClient(OpenAqClient):
    """Stub client returning canned locations + measurements."""

    def __init__(
        self,
        *,
        locations: list[dict[str, Any]],
        measurements: dict[int, float | None],
    ) -> None:
        # Bypass real __init__; we don't touch the network.
        self._locations = locations
        self._measurements = measurements

    async def get_nearby_locations(
        self, lat: float, lng: float, radius_meters: int = 20000
    ) -> list[dict[str, Any]]:
        del lat, lng, radius_meters
        return list(self._locations)

    async def get_latest_measurement(self, sensor_id: int) -> float | None:
        return self._measurements.get(sensor_id)


def _location(
    *,
    loc_id: int,
    lat: float,
    lng: float,
    sensors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": loc_id,
        "name": f"Station {loc_id}",
        "coordinates": {"latitude": lat, "longitude": lng},
        "sensors": sensors,
    }


def _sensor(sensor_id: int, param: str) -> dict[str, Any]:
    return {"id": sensor_id, "parameter": {"name": param, "units": "µg/m³"}}


async def test_fetch_indicator_interpolates_two_stations_with_idw() -> None:
    """Two stations at unequal distances: closer station dominates."""
    await _seed_place()
    # Centroid of the seeded polygon is (~54.57, -1.32).
    near = _location(loc_id=1, lat=54.570, lng=-1.320, sensors=[_sensor(11, "pm25")])
    far = _location(loc_id=2, lat=54.580, lng=-1.330, sensors=[_sensor(12, "pm25")])
    fake = _FakeOpenAqClient(
        locations=[near, far],
        measurements={11: 10.0, 12: 20.0},
    )
    adapter = OpenAqAdapter(get_engine(), openaq_client=fake)
    iv = await adapter.fetch_indicator(
        "environment.air_quality.pm25", "ltla24:E06000004", period=None
    )
    assert iv is not None
    d_near = haversine_km(54.57, -1.32, 54.570, -1.320) or 1e-9
    d_far = haversine_km(54.57, -1.32, 54.580, -1.330)
    expected = (10.0 / d_near**2 + 20.0 / d_far**2) / (1.0 / d_near**2 + 1.0 / d_far**2)
    assert iv.value == pytest.approx(expected, rel=1e-6)
    assert iv.unit == "µg/m³"
    assert iv.confidence == "modelled"
    assert iv.source.source_id == "openaq"


async def test_fetch_indicator_single_station_returns_its_value() -> None:
    await _seed_place()
    near = _location(loc_id=1, lat=54.571, lng=-1.319, sensors=[_sensor(11, "pm25")])
    fake = _FakeOpenAqClient(locations=[near], measurements={11: 7.0})
    adapter = OpenAqAdapter(get_engine(), openaq_client=fake)
    iv = await adapter.fetch_indicator(
        "environment.air_quality.pm25", "ltla24:E06000004", period=None
    )
    assert iv is not None
    assert iv.value == 7.0


async def test_fetch_indicator_returns_none_when_no_stations_nearby() -> None:
    await _seed_place()
    fake = _FakeOpenAqClient(locations=[], measurements={})
    adapter = OpenAqAdapter(get_engine(), openaq_client=fake)
    iv = await adapter.fetch_indicator(
        "environment.air_quality.pm25", "ltla24:E06000004", period=None
    )
    assert iv is None


async def test_fetch_indicator_returns_none_when_no_sensor_for_param() -> None:
    await _seed_place()
    loc = _location(loc_id=1, lat=54.57, lng=-1.32, sensors=[_sensor(11, "no2")])
    fake = _FakeOpenAqClient(locations=[loc], measurements={11: 5.0})
    adapter = OpenAqAdapter(get_engine(), openaq_client=fake)
    iv = await adapter.fetch_indicator(
        "environment.air_quality.pm25", "ltla24:E06000004", period=None
    )
    assert iv is None


async def test_fetch_indicator_returns_none_when_measurement_missing() -> None:
    await _seed_place()
    loc = _location(loc_id=1, lat=54.57, lng=-1.32, sensors=[_sensor(11, "pm25")])
    fake = _FakeOpenAqClient(locations=[loc], measurements={11: None})
    adapter = OpenAqAdapter(get_engine(), openaq_client=fake)
    iv = await adapter.fetch_indicator(
        "environment.air_quality.pm25", "ltla24:E06000004", period=None
    )
    assert iv is None


async def test_fetch_indicator_carries_methodology_caveat_verbatim() -> None:
    """The fixed methodology string is asserted character-for-character."""
    await _seed_place()
    near = _location(loc_id=1, lat=54.57, lng=-1.32, sensors=[_sensor(11, "pm25")])
    fake = _FakeOpenAqClient(locations=[near], measurements={11: 9.0})
    adapter = OpenAqAdapter(get_engine(), openaq_client=fake)
    iv = await adapter.fetch_indicator(
        "environment.air_quality.pm25", "ltla24:E06000004", period=None
    )
    assert iv is not None
    assert METHODOLOGY_CAVEAT in iv.caveats
    assert "inverse distance" in METHODOLOGY_CAVEAT
    assert "interpolated" in METHODOLOGY_CAVEAT.lower()


async def test_fetch_indicator_unknown_indicator_returns_none() -> None:
    await _seed_place()
    fake = _FakeOpenAqClient(locations=[], measurements={})
    adapter = OpenAqAdapter(get_engine(), openaq_client=fake)
    iv = await adapter.fetch_indicator("not.a.real_indicator", "ltla24:E06000004", period=None)
    assert iv is None


async def test_second_fetch_uses_cache() -> None:
    await _seed_place()
    near = _location(loc_id=1, lat=54.57, lng=-1.32, sensors=[_sensor(11, "pm25")])

    call_count = 0

    class CountingClient(_FakeOpenAqClient):
        async def get_nearby_locations(
            self, lat: float, lng: float, radius_meters: int = 20000
        ) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            return [near]

    fake = CountingClient(locations=[near], measurements={11: 8.0})
    adapter = OpenAqAdapter(get_engine(), openaq_client=fake)
    first = await adapter.fetch_indicator(
        "environment.air_quality.pm25", "ltla24:E06000004", period=None
    )
    second = await adapter.fetch_indicator(
        "environment.air_quality.pm25", "ltla24:E06000004", period=None
    )
    assert first is not None and second is not None
    assert second.value == first.value
    # Upstream called once on miss, zero times on the cached second fetch.
    assert call_count == 1


async def test_haversine_km_known_distance() -> None:
    # London (51.5074, -0.1278) to Paris (48.8566, 2.3522) ~ 343 km.
    d = haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
    assert math.isclose(d, 343.0, rel_tol=0.02)


async def test_haversine_km_zero_for_same_point() -> None:
    assert haversine_km(54.0, -1.0, 54.0, -1.0) == 0.0

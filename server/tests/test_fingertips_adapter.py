"""Integration tests for OhidFingertipsAdapter."""

from typing import Any

import httpx
import pytest
from sqlalchemy import text

from soundings.adapters.ohid_fingertips.adapter import OhidFingertipsAdapter
from soundings.adapters.ohid_fingertips.client import FingertipsClient
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_fingertips_source() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, publisher_url, "
                "dataset_url, licence, mode, rate_limit) VALUES "
                "('ohid.fingertips', 'OHID Fingertips', "
                "'Office for Health Improvement and Disparities', "
                "'https://fingertips.phe.org.uk/', "
                "'https://fingertips.phe.org.uk/api', "
                "'OGL-UK-3.0', 'passthrough', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )


def _stockton_rows() -> list[dict[str, Any]]:
    return [
        {
            "AreaCode": "E06000004",
            "AreaName": "Stockton-on-Tees",
            "Sex": "Female",
            "Age": "All ages",
            "Value": 81.2,
            "TimePeriod": "2020 - 22",
            "Year": 2022,
        },
        {
            "AreaCode": "E06000004",
            "AreaName": "Stockton-on-Tees",
            "Sex": "Female",
            "Age": "All ages",
            "Value": 80.8,
            "TimePeriod": "2019 - 21",
            "Year": 2021,
        },
        {
            "AreaCode": "E06000004",
            "AreaName": "Stockton-on-Tees",
            "Sex": "Male",
            "Age": "All ages",
            "Value": 77.4,
            "TimePeriod": "2020 - 22",
            "Year": 2022,
        },
        {
            "AreaCode": "E06000005",
            "AreaName": "Darlington",
            "Sex": "Female",
            "Age": "All ages",
            "Value": 80.0,
            "TimePeriod": "2020 - 22",
            "Year": 2022,
        },
    ]


async def test_fetch_indicator_filters_by_place_and_sex() -> None:
    await _seed_fingertips_source()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=_stockton_rows())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        adapter = OhidFingertipsAdapter(get_engine(), fingertips_client=client)
        iv = await adapter.fetch_indicator(
            "health.life_expectancy.female", "ltla24:E06000004", period=None
        )

    assert iv is not None
    # Latest period for Female + Stockton is 81.2 (2020 - 22).
    assert iv.value == 81.2
    assert iv.unit == "years"
    assert iv.period == "2020 - 22"
    assert iv.source.source_id == "ohid.fingertips"


async def test_fetch_indicator_returns_none_for_unknown_indicator() -> None:
    await _seed_fingertips_source()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=[]))
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        adapter = OhidFingertipsAdapter(get_engine(), fingertips_client=client)
        iv = await adapter.fetch_indicator(
            "health.nope.not.a.real.key", "ltla24:E06000004", period=None
        )
    assert iv is None


async def test_fetch_trend_returns_ordered_series_for_one_sex() -> None:
    await _seed_fingertips_source()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_stockton_rows()))
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        adapter = OhidFingertipsAdapter(get_engine(), fingertips_client=client)
        trend = await adapter.fetch_trend("health.life_expectancy.female", "ltla24:E06000004")

    assert trend is not None
    # Stockton + Female has two rows (2019-21 and 2020-22).
    assert len(trend.points) == 2
    assert trend.points[0].period < trend.points[1].period
    assert trend.points[1].value == 81.2


async def test_fetch_trend_filters_by_period_window() -> None:
    await _seed_fingertips_source()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_stockton_rows()))
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        adapter = OhidFingertipsAdapter(get_engine(), fingertips_client=client)
        trend = await adapter.fetch_trend(
            "health.life_expectancy.female",
            "ltla24:E06000004",
            period_from="2020 - 22",
        )

    assert trend is not None
    assert len(trend.points) == 1
    assert trend.points[0].period == "2020 - 22"


async def test_indicator_payload_is_cached_per_indicator() -> None:
    """One upstream call serves any number of place/sex queries."""
    await _seed_fingertips_source()
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        del request
        return httpx.Response(200, json=_stockton_rows())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        adapter = OhidFingertipsAdapter(get_engine(), fingertips_client=client)
        await adapter.fetch_indicator(
            "health.life_expectancy.female", "ltla24:E06000004", period=None
        )
        await adapter.fetch_indicator(
            "health.life_expectancy.female", "ltla24:E06000005", period=None
        )
        await adapter.fetch_indicator(
            "health.life_expectancy.male", "ltla24:E06000004", period=None
        )
    # Two distinct indicator ids in the mapping (life_expectancy.female and
    # life_expectancy.male share indicator_id=90366); both should hit the
    # cache after the first call. So total = 1 upstream call.
    assert call_count == 1

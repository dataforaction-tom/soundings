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


def _make_record(
    *,
    indicator_id: int,
    sex_id: int,
    sex_name: str,
    age_id: int = 1,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "Grouping": [{"IndicatorId": indicator_id}],
        "Sex": {"Id": sex_id, "Name": sex_name},
        "Age": {"Id": age_id, "Name": "All ages"},
        "Data": rows,
    }


def _row(
    *,
    indicator_id: int,
    area_code: str,
    val: float,
    year: int,
    year_range: int = 3,
) -> dict[str, Any]:
    return {
        "AreaCode": area_code,
        "IndicatorId": indicator_id,
        "Val": val,
        "Year": year,
        "YearRange": year_range,
    }


def _stockton_le_records() -> list[dict[str, Any]]:
    return [
        _make_record(
            indicator_id=90366,
            sex_id=2,
            sex_name="Female",
            rows=[
                _row(indicator_id=90366, area_code="E06000004", val=81.2, year=2024),
                _row(indicator_id=90366, area_code="E06000004", val=80.8, year=2023),
                _row(indicator_id=90366, area_code="E06000005", val=80.0, year=2024),
            ],
        ),
        _make_record(
            indicator_id=90366,
            sex_id=1,
            sex_name="Male",
            rows=[
                _row(indicator_id=90366, area_code="E06000004", val=77.4, year=2024),
            ],
        ),
    ]


async def test_fetch_indicator_filters_by_place_and_sex() -> None:
    await _seed_fingertips_source()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_stockton_le_records()))
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        adapter = OhidFingertipsAdapter(get_engine(), fingertips_client=client)
        iv = await adapter.fetch_indicator(
            "health.life_expectancy.female", "ltla24:E06000004", period=None
        )

    assert iv is not None
    assert iv.value == 81.2
    assert iv.unit == "years"
    # period rendered as "2022 - 24" for a 3-year range ending in 2024.
    assert iv.period == "2022 - 24"
    assert iv.source.source_id == "ohid.fingertips"


async def test_fetch_indicator_returns_none_for_unknown_indicator() -> None:
    await _seed_fingertips_source()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=[]))
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        adapter = OhidFingertipsAdapter(get_engine(), fingertips_client=client)
        iv = await adapter.fetch_indicator("health.not.a.real.key", "ltla24:E06000004", period=None)
    assert iv is None


async def test_fetch_trend_returns_ordered_series_for_one_sex() -> None:
    await _seed_fingertips_source()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_stockton_le_records()))
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        adapter = OhidFingertipsAdapter(get_engine(), fingertips_client=client)
        trend = await adapter.fetch_trend("health.life_expectancy.female", "ltla24:E06000004")

    assert trend is not None
    assert len(trend.points) == 2
    assert trend.points[0].period < trend.points[1].period
    assert trend.points[1].value == 81.2


async def test_group_page_is_cached_per_profile_group_area_type() -> None:
    """One upstream call serves multiple indicator/sex/place queries within
    the same Fingertips (profile, group, area_type) page."""
    await _seed_fingertips_source()
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        del request
        return httpx.Response(200, json=_stockton_le_records())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        adapter = OhidFingertipsAdapter(get_engine(), fingertips_client=client)
        await adapter.fetch_indicator(
            "health.life_expectancy.female", "ltla24:E06000004", period=None
        )
        await adapter.fetch_indicator(
            "health.life_expectancy.male", "ltla24:E06000004", period=None
        )
        await adapter.fetch_indicator(
            "health.life_expectancy.female", "ltla24:E06000005", period=None
        )
    assert call_count == 1

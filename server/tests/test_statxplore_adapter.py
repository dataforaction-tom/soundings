"""Integration tests for DwpStatXploreAdapter."""

import httpx
import pytest
from sqlalchemy import text

from soundings.adapters.dwp_statxplore.adapter import DwpStatXploreAdapter
from soundings.adapters.dwp_statxplore.client import StatXploreClient
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_statxplore_source() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, publisher_url, "
                "dataset_url, licence, mode, rate_limit) VALUES "
                "('dwp.statxplore', 'DWP Stat-Xplore', "
                "'Department for Work and Pensions', "
                "'https://stat-xplore.dwp.gov.uk/', "
                "'https://stat-xplore.dwp.gov.uk/', "
                "'OGL-UK-3.0', 'passthrough', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )


def _sample_payload(values: list[float], periods: list[str]) -> dict:
    measure_id = "str:count:UC_Households:V_F_UC_HOUSEHOLDS"
    return {
        "cubes": {measure_id: {"values": [values]}},
        "fields": [
            {"items": [{"labels": ["E06000004", "Stockton-on-Tees"]}]},
            {"items": [{"labels": [p]} for p in periods]},
        ],
    }


async def test_fetch_indicator_returns_latest_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATXPLORE_API_KEY", "test-key")
    await _seed_statxplore_source()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200, json=_sample_payload([100.0, 120.0, 145.0], ["202401", "202402", "202403"])
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = StatXploreClient(http_client=http)
        adapter = DwpStatXploreAdapter(get_engine(), statxplore_client=client)
        iv = await adapter.fetch_indicator(
            "welfare.universal_credit.households", "ltla24:E06000004", period=None
        )

    assert iv is not None
    assert iv.value == 145.0
    assert iv.period == "202403"
    assert iv.unit == "households"
    assert iv.source.source_id == "dwp.statxplore"


async def test_fetch_indicator_by_explicit_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATXPLORE_API_KEY", "test-key")
    await _seed_statxplore_source()
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json=_sample_payload([100.0, 120.0, 145.0], ["202401", "202402", "202403"]),
        )
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = StatXploreClient(http_client=http)
        adapter = DwpStatXploreAdapter(get_engine(), statxplore_client=client)
        iv = await adapter.fetch_indicator(
            "welfare.universal_credit.households",
            "ltla24:E06000004",
            period="202402",
        )
    assert iv is not None
    assert iv.value == 120.0


async def test_fetch_trend_returns_ordered_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATXPLORE_API_KEY", "test-key")
    await _seed_statxplore_source()
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json=_sample_payload([100.0, 120.0, 145.0], ["202401", "202402", "202403"]),
        )
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = StatXploreClient(http_client=http)
        adapter = DwpStatXploreAdapter(get_engine(), statxplore_client=client)
        trend = await adapter.fetch_trend("welfare.universal_credit.households", "ltla24:E06000004")

    assert trend is not None
    assert len(trend.points) == 3
    assert trend.points[0].period == "202401"
    assert trend.points[-1].value == 145.0


async def test_fetch_trend_filters_by_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATXPLORE_API_KEY", "test-key")
    await _seed_statxplore_source()
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json=_sample_payload([100.0, 120.0, 145.0], ["202401", "202402", "202403"]),
        )
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = StatXploreClient(http_client=http)
        adapter = DwpStatXploreAdapter(get_engine(), statxplore_client=client)
        trend = await adapter.fetch_trend(
            "welfare.universal_credit.households",
            "ltla24:E06000004",
            period_from="202402",
        )
    assert trend is not None
    assert [p.period for p in trend.points] == ["202402", "202403"]


async def test_unknown_indicator_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STATXPLORE_API_KEY", "test-key")
    await _seed_statxplore_source()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    async with httpx.AsyncClient(transport=transport) as http:
        client = StatXploreClient(http_client=http)
        adapter = DwpStatXploreAdapter(get_engine(), statxplore_client=client)
        iv = await adapter.fetch_indicator("welfare.nope.not.real", "ltla24:E06000004", period=None)
    assert iv is None


async def test_per_place_query_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second fetch_indicator call for the same place hits cache."""
    monkeypatch.setenv("STATXPLORE_API_KEY", "test-key")
    await _seed_statxplore_source()
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        del request
        return httpx.Response(200, json=_sample_payload([100.0, 120.0], ["202401", "202402"]))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = StatXploreClient(http_client=http)
        adapter = DwpStatXploreAdapter(get_engine(), statxplore_client=client)
        await adapter.fetch_indicator(
            "welfare.universal_credit.households", "ltla24:E06000004", period=None
        )
        await adapter.fetch_trend("welfare.universal_credit.households", "ltla24:E06000004")
    assert call_count == 1

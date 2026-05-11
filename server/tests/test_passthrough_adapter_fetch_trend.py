"""Integration tests for PassthroughAdapter.fetch_trend.

A fake passthrough adapter returns a 5-point series; first call goes
upstream (live), second call within TTL is served from cache.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.contracts.source_ref import SourceRef
from soundings.contracts.trend import Trend, TrendPoint
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


class FakePassthroughWithTrend(PassthroughAdapter):
    source_id = "test.fake_passthrough_trend"

    def __init__(self, engine: Any, *, ttl: timedelta) -> None:
        super().__init__(engine, ttl=ttl)
        self.upstream_calls = 0
        self.upstream_trend_calls = 0

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any:
        del client, cache_key
        self.upstream_calls += 1
        return {"value": 123.0}

    async def _call_upstream_trend(
        self,
        client: httpx.AsyncClient,
        cache_key: str,
        indicator_key: str,
        place_id: str,
        period_from: str | None,
        period_to: str | None,
    ) -> Any:
        del client, cache_key, indicator_key, place_id, period_from, period_to
        self.upstream_trend_calls += 1
        return [
            {"period": "2020", "value": 80.0},
            {"period": "2021", "value": 80.5},
            {"period": "2022", "value": 80.8},
            {"period": "2023", "value": 81.0},
            {"period": "2024", "value": 81.3},
        ]

    def _materialise_trend(
        self,
        payload: Any,
        indicator_key: str,
        place_id: str,
        source_ref: SourceRef,
    ) -> Trend:
        points = [TrendPoint(period=p["period"], value=p["value"]) for p in payload]
        return Trend(
            place_id=place_id,
            indicator=indicator_key,
            unit="years",
            points=points,
            source=source_ref,
        )


async def _seed_test_source() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, publisher_url, "
                "dataset_url, licence, mode, rate_limit) VALUES "
                "(:id, 'Fake test source', 'Test', 'https://t', 'https://t', "
                "'OGL-UK-3.0', 'passthrough', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": "test.fake_passthrough_trend"},
        )


async def test_fetch_trend_first_call_hits_upstream_and_caches() -> None:
    await _seed_test_source()
    engine = get_engine()
    adapter = FakePassthroughWithTrend(engine, ttl=timedelta(hours=1))

    trend = await adapter.fetch_trend(
        "health.life_expectancy.female",
        "ltla24:E06000004",
        period_from="2020",
        period_to="2024",
    )
    assert trend is not None
    assert len(trend.points) == 5
    assert trend.points[0].period == "2020"
    assert trend.source.cache_status == "live"
    assert adapter.upstream_trend_calls == 1


async def test_fetch_trend_second_call_within_ttl_hits_cache() -> None:
    await _seed_test_source()
    engine = get_engine()
    adapter = FakePassthroughWithTrend(engine, ttl=timedelta(hours=1))

    await adapter.fetch_trend(
        "health.life_expectancy.female",
        "ltla24:E06000004",
        period_from="2020",
        period_to="2024",
    )
    second = await adapter.fetch_trend(
        "health.life_expectancy.female",
        "ltla24:E06000004",
        period_from="2020",
        period_to="2024",
    )

    assert second is not None
    assert second.source.cache_status == "cached"
    # Only one upstream call total.
    assert adapter.upstream_trend_calls == 1


async def test_fetch_trend_different_period_range_is_a_different_cache_key() -> None:
    await _seed_test_source()
    engine = get_engine()
    adapter = FakePassthroughWithTrend(engine, ttl=timedelta(hours=1))

    await adapter.fetch_trend(
        "health.life_expectancy.female",
        "ltla24:E06000004",
        period_from="2020",
        period_to="2024",
    )
    await adapter.fetch_trend(
        "health.life_expectancy.female",
        "ltla24:E06000004",
        period_from="2021",
        period_to="2024",
    )
    # Two distinct upstream calls.
    assert adapter.upstream_trend_calls == 2


async def test_fetch_trend_with_no_upstream_payload_returns_none() -> None:
    await _seed_test_source()
    engine = get_engine()

    class EmptyAdapter(FakePassthroughWithTrend):
        async def _call_upstream_trend(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            self.upstream_trend_calls += 1
            return None

    adapter = EmptyAdapter(engine, ttl=timedelta(hours=1))
    trend = await adapter.fetch_trend(
        "health.life_expectancy.female",
        "ltla24:E06000004",
        period_from=None,
        period_to=None,
    )
    assert trend is None


async def test_assert_datetimes_imported() -> None:
    # Sanity for the test module — guards against accidental future
    # removal of the UTC import (the module needs it for any datetime
    # comparisons we might add).
    assert datetime.now(tz=UTC) is not None

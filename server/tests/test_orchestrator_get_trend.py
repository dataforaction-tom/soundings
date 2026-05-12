"""Tests for IndicatorOrchestrator.get_trend.

Block H core: routes to `adapter.fetch_trend` for passthrough sources and
reads `data.trend_point` directly for loader-mode sources. The
catalogue caveat convention `"series_break:"` populates
`Trend.breaks_in_series` so consumers can disclaim cross-break
comparisons without losing the regular caveats.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text

from soundings.adapters.base import LoaderAdapter, LoaderResult
from soundings.contracts.source_ref import SourceRef
from soundings.contracts.trend import Trend, TrendPoint
from soundings.db.engine import get_engine
from soundings.orchestration.orchestrator import IndicatorOrchestrator
from soundings.orchestration.registry import AdapterRegistry

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_trend_point() -> AsyncIterator[None]:
    """Tests in this file are the only writers to `data.trend_point` at
    the moment; the FK to `geography.place` would otherwise block a
    following test's `DELETE FROM geography.place`."""
    yield
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))


def _ref(source_id: str) -> SourceRef:
    return SourceRef(
        source_id=source_id,
        source_label=source_id,
        publisher="Test",
        retrieved_at=datetime.now(tz=UTC),
        cache_status="cached",
        licence="CC0",
    )


class _LoaderStubAdapter(LoaderAdapter):
    source_id = "test.trend.loader"

    async def load(self, run_id: str | None = None) -> LoaderResult:
        return LoaderResult(rows_written=0)


class _PassthroughStubAdapter:
    """Returns a canned Trend; trend response shape is the contract."""

    source_id = "test.trend.passthrough"
    mode = "passthrough"

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self.calls: list[tuple[str, str, str | None, str | None]] = []
        self.canned: Trend | None = None

    def get_source_ref(self, *, retrieved_at: datetime, cache_status: str) -> SourceRef:
        return _ref(self.source_id)

    async def fetch_trend(
        self,
        indicator_key: str,
        place_id: str,
        period_from: str | None = None,
        period_to: str | None = None,
    ) -> Trend | None:
        self.calls.append((indicator_key, place_id, period_from, period_to))
        return self.canned


async def _seed_catalogue(
    *,
    source_id: str,
    mode: str,
    indicator_key: str,
    available_at: list[str] | None = None,
    caveats: list[str] | None = None,
    unit: str = "value",
) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO catalogue.source "
                "(id, label, publisher, licence, mode, rate_limit) "
                "VALUES (:sid, 'test', 'test', 'CC0', :mode, '{}'::jsonb) "
                "ON CONFLICT (id) DO UPDATE SET mode = EXCLUDED.mode"
            ),
            {"sid": source_id, "mode": mode},
        )
        await conn.execute(
            text(
                "INSERT INTO catalogue.indicator "
                "(key, label, unit, source_id, available_at, caveats, related_keys) "
                "VALUES (:k, 'test', :u, :sid, :avail, CAST(:cav AS jsonb), "
                "ARRAY[]::varchar[]) "
                "ON CONFLICT (key) DO UPDATE SET source_id = EXCLUDED.source_id, "
                "available_at = EXCLUDED.available_at, caveats = EXCLUDED.caveats"
            ),
            {
                "k": indicator_key,
                "u": unit,
                "sid": source_id,
                "avail": available_at or ["ltla24"],
                "cav": _json_dumps(caveats or []),
            },
        )


def _json_dumps(value: list[str]) -> str:
    import json

    return json.dumps(value)


async def _seed_trend_points(
    *,
    place_id: str,
    indicator_key: str,
    source_id: str,
    rows: list[tuple[str, float]],
) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES (:id, 'ltla24', :code, 'Stockton-on-Tees')"
            ),
            {"id": place_id, "code": place_id.split(":", 1)[1]},
        )
        for period, value in rows:
            await conn.execute(
                text(
                    "INSERT INTO data.trend_point "
                    "(place_id, indicator_key, period, value, revised, "
                    "source_id, retrieved_at) "
                    "VALUES (:pid, :ik, :p, :v, false, :sid, NOW())"
                ),
                {
                    "pid": place_id,
                    "ik": indicator_key,
                    "p": period,
                    "v": value,
                    "sid": source_id,
                },
            )


async def test_loader_mode_reads_trend_point_in_period_order() -> None:
    source = "test.trend.loader"
    indicator = "test.trend.metric"
    await _seed_catalogue(source_id=source, mode="loader", indicator_key=indicator)
    await _seed_trend_points(
        place_id="ltla24:E06000004",
        indicator_key=indicator,
        source_id=source,
        rows=[("2022", 95.0), ("2024", 110.0), ("2023", 100.0)],
    )

    registry = AdapterRegistry(get_engine())
    registry.register(source, lambda eng: _LoaderStubAdapter(eng))
    orchestrator = IndicatorOrchestrator(get_engine(), registry)

    result = await orchestrator.get_trend(indicator_key=indicator, place_id="ltla24:E06000004")

    assert result.trend is not None
    assert [p.period for p in result.trend.points] == ["2022", "2023", "2024"]
    assert [p.value for p in result.trend.points] == [95.0, 100.0, 110.0]
    assert result.trend.unit == "value"
    assert result.trend.source.source_id == source


async def test_loader_mode_window_filters_period_from_and_to() -> None:
    source = "test.trend.loader"
    indicator = "test.trend.metric"
    await _seed_catalogue(source_id=source, mode="loader", indicator_key=indicator)
    await _seed_trend_points(
        place_id="ltla24:E06000004",
        indicator_key=indicator,
        source_id=source,
        rows=[
            ("2020", 80.0),
            ("2021", 85.0),
            ("2022", 95.0),
            ("2023", 100.0),
            ("2024", 110.0),
        ],
    )

    registry = AdapterRegistry(get_engine())
    registry.register(source, lambda eng: _LoaderStubAdapter(eng))
    orchestrator = IndicatorOrchestrator(get_engine(), registry)

    result = await orchestrator.get_trend(
        indicator_key=indicator,
        place_id="ltla24:E06000004",
        period_from="2022",
        period_to="2023",
    )

    assert result.trend is not None
    assert [p.period for p in result.trend.points] == ["2022", "2023"]


async def test_passthrough_mode_delegates_to_adapter_fetch_trend() -> None:
    source = "test.trend.passthrough"
    indicator = "test.trend.passthrough_metric"
    await _seed_catalogue(source_id=source, mode="passthrough", indicator_key=indicator)
    await _seed_trend_points(
        place_id="ltla24:E06000004",
        indicator_key=indicator,
        source_id=source,
        rows=[],  # no trend_point rows; passthrough adapter is the source of truth
    )
    canned = Trend(
        place_id="ltla24:E06000004",
        indicator=indicator,
        unit="value",
        points=[TrendPoint(period="2023", value=10.0), TrendPoint(period="2024", value=20.0)],
        source=_ref(source),
    )
    stub = _PassthroughStubAdapter(get_engine())
    stub.canned = canned

    registry = AdapterRegistry(get_engine())
    registry.register(source, lambda eng: stub)
    orchestrator = IndicatorOrchestrator(get_engine(), registry)

    result = await orchestrator.get_trend(
        indicator_key=indicator,
        place_id="ltla24:E06000004",
        period_from="2023",
        period_to="2024",
    )

    assert result.trend is canned
    # Adapter was called with the window args.
    assert stub.calls == [(indicator, "ltla24:E06000004", "2023", "2024")]


async def test_series_break_caveats_populate_breaks_in_series() -> None:
    source = "test.trend.loader"
    indicator = "test.trend.metric"
    await _seed_catalogue(
        source_id=source,
        mode="loader",
        indicator_key=indicator,
        caveats=[
            "series_break: 2022 redefinition shifted the denominator",
            "Survey-based estimate.",
            "series_break: 2024 methodology change",
        ],
    )
    await _seed_trend_points(
        place_id="ltla24:E06000004",
        indicator_key=indicator,
        source_id=source,
        rows=[("2021", 1.0), ("2023", 2.0), ("2024", 3.0)],
    )

    registry = AdapterRegistry(get_engine())
    registry.register(source, lambda eng: _LoaderStubAdapter(eng))
    orchestrator = IndicatorOrchestrator(get_engine(), registry)

    result = await orchestrator.get_trend(indicator_key=indicator, place_id="ltla24:E06000004")

    assert result.trend is not None
    # Series-break caveats land in breaks_in_series (prefix stripped).
    assert result.trend.breaks_in_series == [
        "2022 redefinition shifted the denominator",
        "2024 methodology change",
    ]
    # Non-break caveats stay in the result.caveats list, prefixed with the
    # indicator key (same shape as get_indicators).
    assert any("Survey-based estimate." in c for c in result.caveats)
    # …and don't pollute breaks_in_series.
    assert "Survey-based estimate." not in result.trend.breaks_in_series


async def test_returns_none_trend_when_no_data() -> None:
    source = "test.trend.loader"
    indicator = "test.trend.metric"
    await _seed_catalogue(source_id=source, mode="loader", indicator_key=indicator)
    await _seed_trend_points(
        place_id="ltla24:E06000004",
        indicator_key=indicator,
        source_id=source,
        rows=[],  # no rows
    )

    registry = AdapterRegistry(get_engine())
    registry.register(source, lambda eng: _LoaderStubAdapter(eng))
    orchestrator = IndicatorOrchestrator(get_engine(), registry)

    result = await orchestrator.get_trend(indicator_key=indicator, place_id="ltla24:E06000004")

    assert result.trend is None
    assert result.partial is True
    assert any("no trend" in c.lower() for c in result.caveats)


async def test_level_violation_returns_caveat_not_trend() -> None:
    source = "test.trend.loader"
    indicator = "test.trend.metric"
    await _seed_catalogue(
        source_id=source,
        mode="loader",
        indicator_key=indicator,
        available_at=["ltla24"],  # not lsoa21
    )
    await _seed_trend_points(
        place_id="ltla24:E06000004",
        indicator_key=indicator,
        source_id=source,
        rows=[("2024", 1.0)],
    )
    # Also seed the lsoa21 place we're requesting.
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('lsoa21:E01001234', 'lsoa21', 'E01001234', 'Test LSOA')"
            )
        )

    registry = AdapterRegistry(get_engine())
    registry.register(source, lambda eng: _LoaderStubAdapter(eng))
    orchestrator = IndicatorOrchestrator(get_engine(), registry)

    result = await orchestrator.get_trend(indicator_key=indicator, place_id="lsoa21:E01001234")

    assert result.trend is None
    assert result.partial is True
    assert any("NOT_AVAILABLE" in c or "available_at" in c.lower() for c in result.caveats)

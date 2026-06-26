import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from soundings.adapters.base import LoaderAdapter, LoaderResult
from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.source_ref import SourceRef
from soundings.db.engine import get_engine
from soundings.orchestration.orchestrator import (
    IndicatorOrchestrator,
    OrchestrationResult,
)
from soundings.orchestration.registry import AdapterRegistry

pytestmark = pytest.mark.integration


def _ref(source_id: str = "test.fake") -> SourceRef:
    return SourceRef(
        source_id=source_id,
        source_label=source_id,
        publisher="Test",
        retrieved_at=datetime.now(tz=UTC),
        cache_status="cached",
        licence="CC0",
    )


class _HappyAdapter(LoaderAdapter):
    source_id = "test.fake.happy"

    async def load(self, run_id: str | None = None) -> LoaderResult:
        return LoaderResult(rows_written=0)

    async def fetch_indicator(
        self, indicator_key: str, place_id: str, period: str | None
    ) -> IndicatorValue | None:
        return IndicatorValue(
            place_id=place_id,
            indicator=indicator_key,
            value=42,
            unit="things",
            period=period or "latest",
            source=_ref(self.source_id),
            confidence="official",
        )


class _AngryAdapter(LoaderAdapter):
    source_id = "test.fake.angry"

    async def load(self, run_id: str | None = None) -> LoaderResult:
        return LoaderResult(rows_written=0)

    async def fetch_indicator(
        self, indicator_key: str, place_id: str, period: str | None
    ) -> IndicatorValue | None:
        raise RuntimeError("upstream is on fire")


class _SlowAdapter(LoaderAdapter):
    """Simulates a live external adapter (OSM, OpenAQ) that hangs past the
    orchestrator's soft budget."""

    source_id = "test.fake.slow"

    async def load(self, run_id: str | None = None) -> LoaderResult:
        return LoaderResult(rows_written=0)

    async def fetch_indicator(
        self, indicator_key: str, place_id: str, period: str | None
    ) -> IndicatorValue | None:
        await asyncio.sleep(5)
        return IndicatorValue(
            place_id=place_id,
            indicator=indicator_key,
            value=1,
            unit="things",
            period=period or "latest",
            source=_ref(self.source_id),
            confidence="official",
        )


async def _ensure_indicator(source_id: str, key: str, available_at: list[str]) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO catalogue.source "
                "(id, label, publisher, licence, mode, rate_limit) "
                "VALUES (:sid, 'fake', 'fake', 'CC0', 'loader', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"sid": source_id},
        )
        await conn.execute(
            text(
                "INSERT INTO catalogue.indicator "
                "(key, label, unit, source_id, available_at, caveats, related_keys) "
                "VALUES (:k, 'fake', 'unit', :sid, :avail, '[]'::jsonb, ARRAY[]::varchar[]) "
                "ON CONFLICT (key) DO UPDATE SET source_id = EXCLUDED.source_id"
            ),
            {"k": key, "sid": source_id, "avail": available_at},
        )


async def test_orchestrator_returns_values_and_isolates_failures() -> None:
    engine = get_engine()
    await _ensure_indicator("test.fake.happy", "test.indicator.alpha", ["ltla24"])
    await _ensure_indicator("test.fake.angry", "test.indicator.beta", ["ltla24"])

    registry = AdapterRegistry(engine)
    registry.register("test.fake.happy", lambda eng: _HappyAdapter(eng))
    registry.register("test.fake.angry", lambda eng: _AngryAdapter(eng))

    orchestrator = IndicatorOrchestrator(engine, registry)
    result = await orchestrator.fetch(
        indicator_keys=["test.indicator.alpha", "test.indicator.beta"],
        place_id="ltla24:E06000004",
        period=None,
    )
    assert isinstance(result, OrchestrationResult)
    assert len(result.values) == 1
    assert result.values[0].indicator == "test.indicator.alpha"
    assert len(result.caveats) >= 1
    assert any("test.fake.angry" in c or "test.indicator.beta" in c for c in result.caveats)
    assert result.partial is True


async def test_orchestrator_preserves_fast_values_when_one_adapter_times_out() -> None:
    # Regression: a single slow adapter must not poison fast, already-complete
    # results. Previously the whole gather was wrapped in one wait_for, so any
    # adapter exceeding the budget caused EVERY indicator — including seeded
    # DB-backed ones — to be reported as TimeoutError.
    engine = get_engine()
    await _ensure_indicator("test.fake.happy", "test.indicator.fast", ["ltla24"])
    await _ensure_indicator("test.fake.slow", "test.indicator.slow", ["ltla24"])

    registry = AdapterRegistry(engine)
    registry.register("test.fake.happy", lambda eng: _HappyAdapter(eng))
    registry.register("test.fake.slow", lambda eng: _SlowAdapter(eng))

    orchestrator = IndicatorOrchestrator(engine, registry)
    result = await orchestrator.fetch(
        indicator_keys=["test.indicator.fast", "test.indicator.slow"],
        place_id="ltla24:E06000004",
        period=None,
        timeout=0.5,
    )
    # The fast value survives; only the slow one is dropped to a caveat.
    assert [v.indicator for v in result.values] == ["test.indicator.fast"]
    assert result.partial is True
    assert any("test.indicator.slow" in c for c in result.caveats)


async def test_orchestrator_marks_complete_when_all_succeed() -> None:
    engine = get_engine()
    await _ensure_indicator("test.fake.happy", "test.indicator.gamma", ["ltla24"])
    await _ensure_indicator("test.fake.happy", "test.indicator.delta", ["ltla24"])

    registry = AdapterRegistry(engine)
    registry.register("test.fake.happy", lambda eng: _HappyAdapter(eng))

    orchestrator = IndicatorOrchestrator(engine, registry)
    result = await orchestrator.fetch(
        indicator_keys=["test.indicator.gamma", "test.indicator.delta"],
        place_id="ltla24:E06000004",
        period=None,
    )
    assert len(result.values) == 2
    assert result.partial is False

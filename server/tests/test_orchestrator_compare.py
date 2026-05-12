"""Tests for IndicatorOrchestrator.compare_places.

Block G core: the orchestrator computes rank/percentile against the
**full same-type peer universe**, not just the caller's highlighted
places. For loader-mode adapters this reads directly from
`data.indicator_value`; for passthrough adapters it fans out — with a
soft budget — and adds a caveat when the budget is exceeded.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from soundings.adapters.base import LoaderAdapter, LoaderResult
from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.source_ref import SourceRef
from soundings.db.engine import get_engine
from soundings.orchestration.orchestrator import IndicatorOrchestrator
from soundings.orchestration.registry import AdapterRegistry

pytestmark = pytest.mark.integration


# --- shared fixtures ---------------------------------------------------------


def _ref(source_id: str = "test.compare.loader") -> SourceRef:
    return SourceRef(
        source_id=source_id,
        source_label=source_id,
        publisher="Test",
        retrieved_at=datetime.now(tz=UTC),
        cache_status="cached",
        licence="CC0",
    )


class _LoaderStubAdapter(LoaderAdapter):
    """Minimal loader-mode adapter; orchestrator reads peer values from
    data.indicator_value directly, so this class only needs to look like
    a loader-mode adapter for type discrimination."""

    source_id = "test.compare.loader"

    async def load(self, run_id: str | None = None) -> LoaderResult:
        return LoaderResult(rows_written=0)


class _PassthroughStubAdapter:
    """Minimal passthrough-mode adapter — orchestrator fans out via
    fetch_indicator for the peer universe and counts the calls.
    `mode = "passthrough"` is what tells the orchestrator to fan out."""

    source_id = "test.compare.pt"
    mode = "passthrough"

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self.fetch_count = 0
        self.values_by_place: dict[str, float] = {}

    def get_source_ref(self, *, retrieved_at: datetime, cache_status: str) -> SourceRef:
        return _ref(self.source_id)

    async def fetch_indicator(
        self, indicator_key: str, place_id: str, period: str | None
    ) -> IndicatorValue | None:
        self.fetch_count += 1
        val = self.values_by_place.get(place_id)
        if val is None:
            return None
        return IndicatorValue(
            place_id=place_id,
            indicator=indicator_key,
            value=val,
            unit="things",
            period="2024",
            source=_ref(self.source_id),
            confidence="official",
        )


async def _seed_source_and_indicator(
    *,
    source_id: str = "test.compare.loader",
    mode: str = "loader",
    indicator_key: str = "test.compare.metric",
    available_at: list[str] | None = None,
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
                "VALUES (:k, 'test', :u, :sid, :avail, '[]'::jsonb, "
                "ARRAY[]::varchar[]) "
                "ON CONFLICT (key) DO UPDATE SET source_id = EXCLUDED.source_id, "
                "available_at = EXCLUDED.available_at"
            ),
            {
                "k": indicator_key,
                "u": unit,
                "sid": source_id,
                "avail": available_at or ["ltla24"],
            },
        )


async def _seed_peers_with_values(
    *,
    indicator_key: str,
    source_id: str,
    values_by_code: dict[str, float],
    place_type: str = "ltla24",
    period: str = "2024",
) -> list[str]:
    """Seed N geography.place rows + N data.indicator_value rows. Returns
    the list of soundings place_ids in the order of `values_by_code`."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        place_ids: list[str] = []
        for code, value in values_by_code.items():
            place_id = f"{place_type}:{code}"
            place_ids.append(place_id)
            await conn.execute(
                text(
                    "INSERT INTO geography.place (id, type, code, name) "
                    "VALUES (:id, :pt, :code, :name)"
                ),
                {"id": place_id, "pt": place_type, "code": code, "name": f"Place {code}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO data.indicator_value "
                    "(place_id, indicator_key, period, value, source_id, "
                    "retrieved_at, caveats) "
                    "VALUES (:pid, :ik, :p, :v, :sid, NOW(), '[]'::jsonb)"
                ),
                {
                    "pid": place_id,
                    "ik": indicator_key,
                    "p": period,
                    "v": value,
                    "sid": source_id,
                },
            )
    return place_ids


# --- tests -------------------------------------------------------------------


async def test_percentile_of_median_against_11_peers_is_50() -> None:
    """11 LTLAs with values 100..1100. Median (value=600) ranks 6th of 11
    (5 below + 5 above) and sits exactly at the 50th percentile."""
    indicator = "test.compare.metric"
    source = "test.compare.loader"
    await _seed_source_and_indicator(source_id=source, indicator_key=indicator)
    values = {f"E0600000{i}": float(i * 100) for i in range(1, 12)}
    place_ids = await _seed_peers_with_values(
        indicator_key=indicator, source_id=source, values_by_code=values
    )

    registry = AdapterRegistry(get_engine())
    registry.register(source, lambda eng: _LoaderStubAdapter(eng))
    orchestrator = IndicatorOrchestrator(get_engine(), registry)

    median_place = place_ids[5]  # value 600
    result = await orchestrator.compare_places(
        place_ids=[median_place], indicators=[indicator], basis="percentile"
    )

    assert len(result.comparisons) == 1
    comparison = result.comparisons[0]
    assert comparison.indicator == indicator
    assert comparison.period == "2024"
    assert len(comparison.values) == 1
    cv = comparison.values[0]
    assert cv.place_id == median_place
    assert cv.value == 600.0
    assert cv.rank == 6
    assert cv.percentile == pytest.approx(50.0)


async def test_basis_rank_omits_percentile() -> None:
    indicator = "test.compare.metric"
    source = "test.compare.loader"
    await _seed_source_and_indicator(source_id=source, indicator_key=indicator)
    values = {f"E0600000{i}": float(i * 10) for i in range(1, 6)}
    place_ids = await _seed_peers_with_values(
        indicator_key=indicator, source_id=source, values_by_code=values
    )

    registry = AdapterRegistry(get_engine())
    registry.register(source, lambda eng: _LoaderStubAdapter(eng))
    orchestrator = IndicatorOrchestrator(get_engine(), registry)

    result = await orchestrator.compare_places(
        place_ids=[place_ids[-1]],  # highest value
        indicators=[indicator],
        basis="rank",
    )

    cv = result.comparisons[0].values[0]
    assert cv.rank == 1
    assert cv.percentile is None


async def test_basis_absolute_omits_rank_and_percentile() -> None:
    indicator = "test.compare.metric"
    source = "test.compare.loader"
    await _seed_source_and_indicator(source_id=source, indicator_key=indicator)
    values = {f"E0600000{i}": float(i * 10) for i in range(1, 4)}
    place_ids = await _seed_peers_with_values(
        indicator_key=indicator, source_id=source, values_by_code=values
    )

    registry = AdapterRegistry(get_engine())
    registry.register(source, lambda eng: _LoaderStubAdapter(eng))
    orchestrator = IndicatorOrchestrator(get_engine(), registry)

    result = await orchestrator.compare_places(
        place_ids=[place_ids[0]], indicators=[indicator], basis="absolute"
    )

    cv = result.comparisons[0].values[0]
    assert cv.value == 10.0
    assert cv.rank is None
    assert cv.percentile is None


async def test_basis_rate_divides_value_by_population() -> None:
    """Rate basis divides each peer's value by population.total
    (×1000) before ranking, so a small place with a high count gets a
    higher rate than a large place with the same count."""
    indicator = "test.compare.metric"
    source = "test.compare.loader"
    await _seed_source_and_indicator(source_id=source, indicator_key=indicator)
    # Population indicator must also exist in the catalogue/source rows so
    # the orchestrator's SELECT for population.total works.
    await _seed_source_and_indicator(
        source_id="ons.mid_year_estimates",
        indicator_key="population.total",
        unit="people",
    )
    # Build: 3 places, value 600 each, populations 1000, 2000, 3000.
    # Expected rates per 1000 pop: 600, 300, 200.
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        for code, pop in [("E06000001", 1000.0), ("E06000002", 2000.0), ("E06000003", 3000.0)]:
            place_id = f"ltla24:{code}"
            await conn.execute(
                text(
                    "INSERT INTO geography.place (id, type, code, name) "
                    "VALUES (:id, 'ltla24', :code, :name)"
                ),
                {"id": place_id, "code": code, "name": f"Place {code}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO data.indicator_value "
                    "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) "
                    "VALUES (:pid, :ik, '2024', 600, :sid, NOW(), '[]'::jsonb)"
                ),
                {"pid": place_id, "ik": indicator, "sid": source},
            )
            await conn.execute(
                text(
                    "INSERT INTO data.indicator_value "
                    "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) "
                    "VALUES (:pid, 'population.total', '2024', :pop, "
                    "'ons.mid_year_estimates', NOW(), '[]'::jsonb)"
                ),
                {"pid": place_id, "pop": pop},
            )

    registry = AdapterRegistry(get_engine())
    registry.register(source, lambda eng: _LoaderStubAdapter(eng))
    orchestrator = IndicatorOrchestrator(get_engine(), registry)

    result = await orchestrator.compare_places(
        place_ids=["ltla24:E06000001", "ltla24:E06000003"],
        indicators=[indicator],
        basis="rate",
    )

    cv_by_id = {cv.place_id: cv for cv in result.comparisons[0].values}
    # 600/1000 * 1000 = 600
    assert cv_by_id["ltla24:E06000001"].value == pytest.approx(600.0)
    # 600/3000 * 1000 = 200
    assert cv_by_id["ltla24:E06000003"].value == pytest.approx(200.0)
    # Smaller place has higher rate → rank 1
    assert cv_by_id["ltla24:E06000001"].rank == 1
    assert cv_by_id["ltla24:E06000003"].rank == 3


async def test_passthrough_budget_exceeded_adds_caveat_and_uses_caller_slice() -> None:
    """When a passthrough adapter would need > 200 peer fetches, the
    orchestrator falls back to ranking the caller's highlighted places
    against each other, with a clear caveat about the methodology."""
    indicator = "test.compare.passthrough_metric"
    source = "test.compare.pt"
    await _seed_source_and_indicator(source_id=source, mode="passthrough", indicator_key=indicator)
    # Seed 300 peers — orchestrator should refuse the fan-out.
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        for i in range(300):
            code = f"E060{i:05d}"
            await conn.execute(
                text(
                    "INSERT INTO geography.place (id, type, code, name) "
                    "VALUES (:id, 'ltla24', :code, :name)"
                ),
                {"id": f"ltla24:{code}", "code": code, "name": f"Place {code}"},
            )

    stub = _PassthroughStubAdapter(get_engine())
    # Give caller-provided places values; nothing else.
    stub.values_by_place = {
        "ltla24:E06000000": 50.0,
        "ltla24:E06000001": 30.0,
    }
    registry = AdapterRegistry(get_engine())
    registry.register(source, lambda eng: stub)
    orchestrator = IndicatorOrchestrator(get_engine(), registry)

    result = await orchestrator.compare_places(
        place_ids=["ltla24:E06000000", "ltla24:E06000001"],
        indicators=[indicator],
        basis="percentile",
    )

    assert result.comparisons, "should still return a Comparison for the caller slice"
    cv_by_id = {cv.place_id: cv for cv in result.comparisons[0].values}
    assert cv_by_id["ltla24:E06000000"].value == 50.0
    assert cv_by_id["ltla24:E06000001"].value == 30.0
    # Within the caller slice of 2: 50.0 is rank 1, 30.0 is rank 2.
    assert cv_by_id["ltla24:E06000000"].rank == 1
    assert cv_by_id["ltla24:E06000001"].rank == 2
    # Caveat must surface the budget reason.
    joined = " ".join(result.caveats)
    assert "caller-provided peers only" in joined
    assert "passthrough" in joined
    # Should NOT have hammered the upstream with 300 fetches.
    assert stub.fetch_count <= len(["ltla24:E06000000", "ltla24:E06000001"])


async def test_no_value_for_place_yields_none_value_and_no_rank() -> None:
    """A place with no row in data.indicator_value gets value=None and no
    rank/percentile, but the orchestrator still returns a Comparison so
    callers see the slot."""
    indicator = "test.compare.metric"
    source = "test.compare.loader"
    await _seed_source_and_indicator(source_id=source, indicator_key=indicator)
    values = {f"E0600000{i}": float(i * 10) for i in range(1, 4)}
    place_ids = await _seed_peers_with_values(
        indicator_key=indicator, source_id=source, values_by_code=values
    )

    # Add a place with no indicator_value row.
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:E06099999', 'ltla24', 'E06099999', 'Missing')"
            )
        )

    registry = AdapterRegistry(get_engine())
    registry.register(source, lambda eng: _LoaderStubAdapter(eng))
    orchestrator = IndicatorOrchestrator(get_engine(), registry)

    result = await orchestrator.compare_places(
        place_ids=[place_ids[0], "ltla24:E06099999"],
        indicators=[indicator],
        basis="percentile",
    )

    cv_by_id = {cv.place_id: cv for cv in result.comparisons[0].values}
    assert cv_by_id["ltla24:E06099999"].value is None
    assert cv_by_id["ltla24:E06099999"].rank is None
    assert cv_by_id["ltla24:E06099999"].percentile is None

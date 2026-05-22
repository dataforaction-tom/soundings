import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from soundings.adapters.mhclg_imd2025.adapter import MhclgImd2025Adapter
from soundings.adapters.ons_mid_year_estimates.adapter import OnsMidYearEstimatesAdapter
from soundings.db.engine import get_engine
from soundings.orchestration.orchestrator import IndicatorOrchestrator
from soundings.orchestration.registry import AdapterRegistry
from soundings.tools.get_indicators import GetIndicatorsInput, get_indicators

pytestmark = pytest.mark.integration


async def _seed_two_indicators() -> None:
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.loader_run"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:E06000004', 'ltla24', 'E06000004', 'Stockton-on-Tees')"
            )
        )
        run_a = uuid.uuid4()
        run_b = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO data.loader_run "
                "(id, source_id, started_at, finished_at, status, rows_written) VALUES "
                "(:a, 'ons.mid_year_estimates', :s, :f, 'ok', 1), "
                "(:b, 'mhclg.imd2025', :s, :f, 'ok', 1)"
            ),
            {"a": run_a, "b": run_b, "s": now - timedelta(minutes=5), "f": now},
        )
        await conn.execute(
            text(
                "INSERT INTO data.indicator_value "
                "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) VALUES "
                "('ltla24:E06000004', 'population.total', '2024', 200000, 'ons.mid_year_estimates', :ret, '[]'::jsonb), "
                "('ltla24:E06000004', 'deprivation.imd.score', '2025', 24.0, 'mhclg.imd2025', :ret, '[]'::jsonb)"
            ),
            {"ret": now},
        )


async def test_get_indicators_returns_tall_results_with_sources() -> None:
    engine = get_engine()
    await _seed_two_indicators()

    registry = AdapterRegistry(engine)
    registry.register("ons.mid_year_estimates", OnsMidYearEstimatesAdapter)
    registry.register("mhclg.imd2025", MhclgImd2025Adapter)
    orchestrator = IndicatorOrchestrator(engine, registry)

    result = await get_indicators(
        GetIndicatorsInput(
            place_id="ltla24:E06000004",
            indicators=["population.total", "deprivation.imd.score"],
        ),
        orchestrator,
    )
    assert len(result.results) == 2
    by_key = {r.indicator: r for r in result.results}
    assert by_key["population.total"].value == 200000
    assert by_key["deprivation.imd.score"].value == 24.0
    assert all(r.source.source_id for r in result.results)
    # Two distinct sources → two distinct source refs.
    assert len({s.source_id for s in result.sources}) == 2


async def test_get_indicators_wide_format_groups_by_place() -> None:
    engine = get_engine()
    await _seed_two_indicators()

    registry = AdapterRegistry(engine)
    registry.register("ons.mid_year_estimates", OnsMidYearEstimatesAdapter)
    registry.register("mhclg.imd2025", MhclgImd2025Adapter)
    orchestrator = IndicatorOrchestrator(engine, registry)

    result = await get_indicators(
        GetIndicatorsInput(
            place_id="ltla24:E06000004",
            indicators=["population.total", "deprivation.imd.score"],
            format="wide",
        ),
        orchestrator,
    )
    assert result.wide is not None
    assert result.wide.place_id == "ltla24:E06000004"
    assert result.wide.indicators["population.total"] == 200000
    assert result.wide.indicators["deprivation.imd.score"] == 24.0
    # Tall is still populated alongside wide so consumers can pick.
    assert len(result.results) == 2


async def test_get_indicators_surfaces_catalogue_caveats() -> None:
    engine = get_engine()
    await _seed_two_indicators()
    # Stamp a catalogue-level caveat onto one of the indicators.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE catalogue.indicator SET caveats = '[\"Mid-year estimates are revised after each Census.\"]'::jsonb "
                "WHERE key = 'population.total'"
            )
        )

    registry = AdapterRegistry(engine)
    registry.register("ons.mid_year_estimates", OnsMidYearEstimatesAdapter)
    registry.register("mhclg.imd2025", MhclgImd2025Adapter)
    orchestrator = IndicatorOrchestrator(engine, registry)

    result = await get_indicators(
        GetIndicatorsInput(
            place_id="ltla24:E06000004",
            indicators=["population.total"],
        ),
        orchestrator,
    )
    assert any("Mid-year estimates are revised" in c for c in result.caveats)

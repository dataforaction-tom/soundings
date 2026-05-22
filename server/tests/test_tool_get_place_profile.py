import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from soundings.adapters.mhclg_imd2025.adapter import MhclgImd2025Adapter
from soundings.adapters.ons_mid_year_estimates.adapter import OnsMidYearEstimatesAdapter
from soundings.db.engine import get_engine
from soundings.orchestration.orchestrator import IndicatorOrchestrator
from soundings.orchestration.registry import AdapterRegistry
from soundings.tools.get_place_profile import GetPlaceProfileInput, get_place_profile

pytestmark = pytest.mark.integration


async def _seed() -> None:
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
        run = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO data.loader_run "
                "(id, source_id, started_at, finished_at, status, rows_written) "
                "VALUES (:id, 'ons.mid_year_estimates', :s, :f, 'ok', 1)"
            ),
            {"id": run, "s": now - timedelta(minutes=5), "f": now},
        )
        await conn.execute(
            text(
                "INSERT INTO data.indicator_value "
                "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) VALUES "
                "('ltla24:E06000004', 'population.total', '2024', 200000, 'ons.mid_year_estimates', :ret, '[]'::jsonb)"
            ),
            {"ret": now},
        )


async def test_get_place_profile_resolves_population_domain() -> None:
    engine = get_engine()
    await _seed()

    registry = AdapterRegistry(engine)
    registry.register("ons.mid_year_estimates", OnsMidYearEstimatesAdapter)
    registry.register("mhclg.imd2025", MhclgImd2025Adapter)
    orchestrator = IndicatorOrchestrator(engine, registry)

    result = await get_place_profile(
        GetPlaceProfileInput(place_id="ltla24:E06000004", include=["population"]),
        orchestrator,
        engine,
    )
    assert result.place.id == "ltla24:E06000004"
    assert result.place.name == "Stockton-on-Tees"
    by_key = {v.indicator: v.value for v in result.indicators}
    assert by_key.get("population.total") == 200000
    # Every indicator value carries an explicit confidence label.
    assert all(
        iv.confidence in ("official", "modelled", "experimental") for iv in result.indicators
    )
    # MYE is a loader-mode source publishing official statistics.
    assert result.indicators[0].confidence == "official"

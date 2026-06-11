import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from soundings.adapters.ons_mid_year_estimates.adapter import OnsMidYearEstimatesAdapter
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_one_row(value: float = 200000) -> None:
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.loader_run"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text("INSERT INTO geography.place (id, type, code, name) VALUES (:id, :t, :c, :n)"),
            {
                "id": "ltla24:E06000004",
                "t": "ltla24",
                "c": "E06000004",
                "n": "Stockton-on-Tees",
            },
        )
        run_id = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO data.loader_run "
                "(id, source_id, started_at, finished_at, status, rows_written) "
                "VALUES (:id, 'ons.mid_year_estimates', :s, :f, 'ok', 1)"
            ),
            {"id": run_id, "s": now - timedelta(minutes=5), "f": now},
        )
        await conn.execute(
            text(
                "INSERT INTO data.indicator_value "
                "(place_id, indicator_key, period, value, source_id, retrieved_at, loader_run_id, caveats) "
                "VALUES (:pid, :ik, '2024', :v, 'ons.mid_year_estimates', :ret, :rid, '[]'::jsonb)"
            ),
            {
                "pid": "ltla24:E06000004",
                "ik": "population.total",
                "v": value,
                "ret": now,
                "rid": run_id,
            },
        )


async def test_mye_adapter_fetch_indicator_returns_seeded_value() -> None:
    engine = get_engine()
    await _seed_one_row()

    adapter = OnsMidYearEstimatesAdapter(engine)
    iv = await adapter.fetch_indicator("population.total", "ltla24:E06000004", None)
    assert iv is not None
    assert iv.value == 200000
    assert iv.source.source_id == "ons.mid_year_estimates"
    assert iv.source.cache_status in ("cached", "stale", "live")

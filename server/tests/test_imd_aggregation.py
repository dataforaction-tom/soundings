from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from soundings.adapters.mhclg_imd2025.aggregation import aggregate_imd_to_ltla
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_two_lsoas_in_one_ltla() -> None:
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        for place_id, place_type, code, name in [
            ("lsoa21:E01012018", "lsoa21", "E01012018", "Stockton 010A"),
            ("lsoa21:E01012019", "lsoa21", "E01012019", "Stockton 010B"),
            ("ltla24:E06000004", "ltla24", "E06000004", "Stockton-on-Tees"),
        ]:
            await conn.execute(
                text("INSERT INTO geography.place (id, type, code, name) VALUES (:id, :t, :c, :n)"),
                {"id": place_id, "t": place_type, "c": code, "n": name},
            )
        for child, parent in [
            ("lsoa21:E01012018", "ltla24:E06000004"),
            ("lsoa21:E01012019", "ltla24:E06000004"),
        ]:
            await conn.execute(
                text("INSERT INTO geography.place_hierarchy (child_id, parent_id) VALUES (:c, :p)"),
                {"c": child, "p": parent},
            )
        # MYE populations: 2000 and 1000.
        await conn.execute(
            text(
                "INSERT INTO data.indicator_value "
                "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) "
                "VALUES "
                "('lsoa21:E01012018', 'population.total', '2024', 2000, 'ons.mid_year_estimates', :ret, '[]'::jsonb), "
                "('lsoa21:E01012019', 'population.total', '2024', 1000, 'ons.mid_year_estimates', :ret, '[]'::jsonb)"
            ),
            {"ret": now},
        )
        # IMD scores: 30 and 12. Weighted avg = (30*2000 + 12*1000) / 3000 = 24.
        await conn.execute(
            text(
                "INSERT INTO data.indicator_value "
                "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) "
                "VALUES "
                "('lsoa21:E01012018', 'deprivation.imd.score', '2025', 30, 'mhclg.imd2025', :ret, '[]'::jsonb), "
                "('lsoa21:E01012019', 'deprivation.imd.score', '2025', 12, 'mhclg.imd2025', :ret, '[]'::jsonb)"
            ),
            {"ret": now},
        )


async def test_population_weighted_aggregation_writes_ltla_row() -> None:
    engine = get_engine()
    await _seed_two_lsoas_in_one_ltla()

    aggregated = await aggregate_imd_to_ltla(engine)
    assert aggregated >= 1

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT value FROM data.indicator_value "
                    "WHERE place_id = 'ltla24:E06000004' "
                    "AND indicator_key = 'deprivation.imd.score' "
                    "AND source_id = 'mhclg.imd2025'"
                )
            )
        ).first()
    assert row is not None
    assert float(row.value) == 24.0

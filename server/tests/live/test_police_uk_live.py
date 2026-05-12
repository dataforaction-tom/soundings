"""Live test for police_uk against the real data.police.uk API.

Marker `live` — runs nightly, not in PR CI. No auth required.

Seeds an LTLA polygon containing Stockton-on-Tees' approximate
centroid plus a plausible `population.total` row, then asks the
adapter for the rolling 12-month recorded crime rate. Asserts the
returned rate sits in a generous plausible window; tightens the
budget for "this LTLA's centroid sits inside a force boundary and
police.uk is publishing crimes" rather than checking an exact value.

If this test starts failing, look at: police.uk publication outage,
a force boundary change excluding Stockton, or our centroid drifting
off the polygon (PostGIS quirk).
"""

import pytest
from sqlalchemy import text

from soundings.adapters.police_uk.adapter import (
    METHODOLOGY_CAVEAT,
    PoliceUkAdapter,
)
from soundings.db.engine import get_engine

pytestmark = [pytest.mark.live, pytest.mark.integration]

STOCKTON_PLACE_ID = "ltla24:E06000004"
STOCKTON_POPULATION = 196_000.0


async def _seed_stockton() -> None:
    """Stockton-on-Tees centroid is roughly (54.57, -1.32). Seed a small
    polygon around it; ST_Centroid of this square gives lat/lng inside
    the Cleveland Police force area, which means /crimes-street returns
    real data."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name, geom) "
                "VALUES (:id, 'ltla24', 'E06000004', 'Stockton-on-Tees', "
                "ST_Multi(ST_GeomFromText("
                "'POLYGON((-1.34 54.55, -1.30 54.55, -1.30 54.59, "
                "-1.34 54.59, -1.34 54.55))', 4326)))"
            ),
            {"id": STOCKTON_PLACE_ID},
        )
        await conn.execute(
            text(
                "INSERT INTO data.indicator_value "
                "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) "
                "VALUES (:pid, 'population.total', '2024', :val, "
                "'ons.mid_year_estimates', NOW(), '[]'::jsonb)"
            ),
            {"pid": STOCKTON_PLACE_ID, "val": STOCKTON_POPULATION},
        )


async def test_police_uk_adapter_returns_plausible_crime_rate() -> None:
    await _seed_stockton()
    adapter = PoliceUkAdapter(get_engine())
    iv = await adapter.fetch_indicator("crime.recorded_crime_rate", STOCKTON_PLACE_ID, period=None)

    assert iv is not None, "police.uk returned no crimes near the Stockton centroid"
    assert iv.value is not None
    # English LTLA recorded crime rate is typically 50-150 per 1,000 over a
    # rolling 12 months. Tolerate 10-300 to absorb police.uk publication
    # gaps and centroid-window undercount on a synthetic polygon.
    assert 10 < iv.value < 300, f"implausible crime rate: {iv.value}"
    assert iv.unit == "per 1,000 population"
    assert iv.source.source_id == "police_uk"
    assert METHODOLOGY_CAVEAT in iv.caveats

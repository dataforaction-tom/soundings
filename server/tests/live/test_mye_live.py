"""Live test for ons.mid_year_estimates against the real Nomis API.

Skipped on PRs (marker `live`); runs nightly. Asserts the adapter can hit
Nomis end-to-end and produce a plausible value for a known LTLA. The exact
value is not pinned — that's the point of the live check, to catch when
Nomis renames a dataset or measure code.
"""

import pytest
from sqlalchemy import text

from soundings.adapters.ons_mid_year_estimates.adapter import OnsMidYearEstimatesAdapter
from soundings.db.engine import get_engine

pytestmark = [pytest.mark.live, pytest.mark.integration]


async def test_mye_adapter_returns_plausible_population_for_stockton() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
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

    adapter = OnsMidYearEstimatesAdapter(
        engine,
        indicator_keys=["population.total"],
        place_filter=["ltla24:E06000004"],
    )
    result = await adapter.load()
    assert result.rows_written >= 1, "loader produced no rows from real Nomis"

    iv = await adapter.fetch_indicator("population.total", "ltla24:E06000004", None)
    assert iv is not None
    # Stockton-on-Tees is around 200k; allow generous range for revisions.
    assert 100_000 < (iv.value or 0) < 500_000, f"implausible value: {iv.value}"

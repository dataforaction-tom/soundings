"""Live test for ons.census2021 against the real Nomis API."""

import pytest
from sqlalchemy import text

from soundings.adapters.ons_census2021.adapter import OnsCensus2021Adapter
from soundings.db.engine import get_engine

pytestmark = [pytest.mark.live, pytest.mark.integration]


async def test_census_adapter_returns_plausible_share_for_stockton() -> None:
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
                "VALUES ('ltla24:E06000004', 'ltla24', 'E06000004', 'Stockton-on-Tees')"
            )
        )

    adapter = OnsCensus2021Adapter(
        engine,
        indicator_keys=["population.households.lone_parent_share"],
        place_filter=["ltla24:E06000004"],
    )
    result = await adapter.load()
    assert result.rows_written >= 1, "loader produced no rows from real Nomis"

    iv = await adapter.fetch_indicator(
        "population.households.lone_parent_share", "ltla24:E06000004", None
    )
    assert iv is not None
    # Lone-parent share is a fraction. Allow a generous range; the live
    # test is a smoke check, not a value contract.
    assert 0 <= (iv.value or 0) <= 1, f"implausible share: {iv.value}"

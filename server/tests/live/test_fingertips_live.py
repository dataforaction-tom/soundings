"""Live test for ohid.fingertips against the real Fingertips API.

Marker `live` — runs nightly, not in PR CI. Asserts the adapter can
hit Fingertips and produce a plausible value for Stockton-on-Tees.
"""

import pytest
from sqlalchemy import text

from soundings.adapters.ohid_fingertips.adapter import OhidFingertipsAdapter
from soundings.db.engine import get_engine

pytestmark = [pytest.mark.live, pytest.mark.integration]


async def test_fingertips_adapter_returns_plausible_life_expectancy() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:E06000004', 'ltla24', 'E06000004', "
                "'Stockton-on-Tees')"
            )
        )

    adapter = OhidFingertipsAdapter(engine)
    iv = await adapter.fetch_indicator(
        "health.life_expectancy.female", "ltla24:E06000004", period=None
    )

    assert iv is not None, "Fingertips returned no female life expectancy for Stockton"
    # Female life expectancy in England LAs is roughly 78–86.
    assert iv.value is not None
    assert 75 < iv.value < 90, f"implausible value: {iv.value}"
    assert iv.unit == "years"

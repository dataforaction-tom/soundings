"""Live test for ons.aps against the real Nomis API.

Marker `live` — runs nightly, not in PR CI. No auth strictly required;
sets `NOMIS_API_KEY` opportunistically (higher rate limit) if available.

Asserts a plausible Stockton-on-Tees employment rate (0.5–0.85 fraction).
Field codes in `catalogue/nomis-mapping.yaml` (variable/sex/age) are
plausible-but-unverified; if this test fails the most likely cause is a
mismatched APS field code rather than an API outage.
"""

import pytest
from sqlalchemy import text

from soundings.adapters.ons_aps.adapter import OnsApsAdapter
from soundings.db.engine import get_engine

pytestmark = [pytest.mark.live, pytest.mark.integration]


async def test_aps_adapter_returns_plausible_employment_rate() -> None:
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

    adapter = OnsApsAdapter(get_engine())
    iv = await adapter.fetch_indicator("economy.employment_rate", "ltla24:E06000004", period=None)

    assert iv is not None, "APS returned no employment rate for Stockton-on-Tees"
    assert iv.value is not None
    # English LTLA employment rate (16-64) typically sits in 0.55-0.82.
    # Widen to 0.5-0.85 to absorb survey noise and mapping field code drift.
    assert 0.5 < iv.value < 0.85, f"implausible employment rate: {iv.value}"
    assert iv.source.source_id == "ons.aps"

"""Live test for ohid.fingertips against the real Fingertips API.

Marker `live` — runs nightly, not in PR CI. Asserts the adapter can
hit Fingertips and produce a plausible value for Stockton-on-Tees.

**Currently skipped.** Fingertips' `/api/all_data/json/by_indicator_id`
endpoint that this client uses now returns 500; the live data
endpoints require `profile_id` + `group_id` which we don't yet
record per indicator in `catalogue/fingertips-mapping.yaml`. Tracked
in PLAN.md "Open questions" — once the mapping carries profile/group
IDs and the client targets the right endpoint
(`latest_data/all_indicators_in_profile_group_for_child_areas`),
flip this off skip and re-run.
"""

import pytest
from sqlalchemy import text

from soundings.adapters.ohid_fingertips.adapter import OhidFingertipsAdapter
from soundings.db.engine import get_engine

pytestmark = [
    pytest.mark.live,
    pytest.mark.integration,
    pytest.mark.skip(
        reason="Fingertips data endpoint pattern needs profile_id + group_id; "
        "see PLAN.md Phase 3 follow-ups."
    ),
]


async def test_fingertips_adapter_returns_plausible_life_expectancy() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
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

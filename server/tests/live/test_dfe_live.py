"""Live test for dfe.explore against the real DfE EES API.

Marker `live` — runs nightly, not in PR CI.

DfE rotates dataset UUIDs on annual republication, so this test
asserts a plausible FSM eligibility share for an English LTLA
rather than checking an exact value. When the test fails it
likely means the data_set_id (or indicator_id) pinned in
catalogue/dfe-mapping.yaml has been retired and needs to be
updated to the current dataset UUID.

Indicator IDs in the mapping are placeholders pending discovery
via the live API — this test will currently fail until those are
filled. That's the intended failure mode.
"""

import pytest
from sqlalchemy import text

from soundings.adapters.dfe_explore.adapter import DfeExploreAdapter
from soundings.db.engine import get_engine

pytestmark = [pytest.mark.live, pytest.mark.integration]


async def test_dfe_adapter_returns_plausible_fsm_share() -> None:
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

    adapter = DfeExploreAdapter(engine)
    iv = await adapter.fetch_indicator(
        "education.fsm_eligibility_share", "ltla24:E06000004", period=None
    )

    assert iv is not None, "DfE EES returned no FSM share for Stockton-on-Tees"
    assert iv.value is not None
    # FSM eligibility shares in English LAs typically 0.10–0.45.
    # Use a wider 0–1 range to tolerate units in either proportion or %.
    assert 0 < iv.value < 100, f"implausible FSM value: {iv.value}"
    assert iv.unit == "proportion"
    assert iv.source.source_id == "dfe.explore"

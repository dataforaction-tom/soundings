"""Live test for mhclg.imd2025 against the real gov.uk download."""

import pytest
from sqlalchemy import text

from soundings.adapters.mhclg_imd2025.adapter import MhclgImd2025Adapter
from soundings.db.engine import get_engine

pytestmark = [pytest.mark.live, pytest.mark.integration]


async def test_imd_loader_downloads_and_parses_real_workbook() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('lsoa21:E01012018', 'lsoa21', 'E01012018', 'Stockton 010A')"
            )
        )

    adapter = MhclgImd2025Adapter(engine)
    result = await adapter.load()
    assert result.rows_written > 0, "real IMD download produced no rows"

    iv = await adapter.fetch_indicator(
        "deprivation.imd.score", "lsoa21:E01012018", None
    )
    assert iv is not None
    # IMD scores in England range roughly 0–80; allow generous bounds.
    assert 0 <= (iv.value or -1) <= 100

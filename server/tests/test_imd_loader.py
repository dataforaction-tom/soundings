from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, text

from soundings.adapters.mhclg_imd2025.loader import MhclgImd2025Loader
from soundings.db.engine import get_engine
from soundings.db.models.data import IndicatorValue

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).parent / "fixtures" / "imd" / "imd2025_sample.xlsx"


async def _seed_environment() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        for place_id, place_type, code, name in [
            ("lsoa21:E01012018", "lsoa21", "E01012018", "Stockton 010A"),
            ("lsoa21:E01012019", "lsoa21", "E01012019", "Stockton 010B"),
            ("lsoa21:E01000001", "lsoa21", "E01000001", "City of London 001A"),
        ]:
            await conn.execute(
                text("INSERT INTO geography.place (id, type, code, name) VALUES (:id, :t, :c, :n)"),
                {"id": place_id, "t": place_type, "c": code, "n": name},
            )


async def test_imd_loader_writes_lsoa_indicator_rows() -> None:
    engine = get_engine()
    await _seed_environment()
    blob = FIXTURE.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=blob)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        loader = MhclgImd2025Loader(engine, http_client=http)
        result = await loader.load()

    # 3 LSOAs × 8 indicators = 24 rows
    assert result.rows_written == 24

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(IndicatorValue.place_id, IndicatorValue.indicator_key, IndicatorValue.value)
                .where(IndicatorValue.indicator_key == "deprivation.imd.score")
                .order_by(IndicatorValue.place_id)
            )
        ).all()
    by_place = {r.place_id: float(r.value) for r in rows}
    assert by_place["lsoa21:E01012018"] == 35.5
    assert by_place["lsoa21:E01000001"] == 5.4

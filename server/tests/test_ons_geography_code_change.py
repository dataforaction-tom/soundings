import pytest
from sqlalchemy import select, text

from soundings.adapters.ons_geography.code_change_loader import (
    OnsGeographyCodeChangeLoader,
)
from soundings.db.engine import get_engine
from soundings.db.models.geography import CodeChange

pytestmark = pytest.mark.integration

SAMPLE_CSV = b"""GEOGCD_O,GEOGCD_N,GEOGCHGTYPE,EFFECTIVE_DATE,NOTES
E07000004,E06000060,Replacement,2020-04-01,Buckinghamshire UA created
E07000005,E06000060,Replacement,2020-04-01,Buckinghamshire UA created
E08000020,E08000037,Reorganisation,2018-04-01,Gateshead boundary change
"""


async def test_code_change_loader_inserts_rows() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM geography.code_change"))

    loader = OnsGeographyCodeChangeLoader(engine)
    result = await loader.load_from_bytes(SAMPLE_CSV)
    assert result.rows_written == 3

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(
                    CodeChange.old_code,
                    CodeChange.new_code,
                    CodeChange.change_type,
                ).order_by(CodeChange.id)
            )
        ).all()
    assert (rows[0].old_code, rows[0].new_code) == ("E07000004", "E06000060")
    assert rows[2].change_type == "Reorganisation"


async def test_code_change_loader_is_idempotent() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM geography.code_change"))

    loader = OnsGeographyCodeChangeLoader(engine)
    await loader.load_from_bytes(SAMPLE_CSV)
    await loader.load_from_bytes(SAMPLE_CSV)
    async with engine.connect() as conn:
        n = (await conn.execute(text("SELECT count(*) FROM geography.code_change"))).scalar_one()
    assert n == 3

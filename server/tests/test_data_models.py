import pytest
from sqlalchemy import select

from soundings.db.engine import get_engine
from soundings.db.models.data import (
    GrantRecord,
    IndicatorValue,
    LoaderRun,
    Organisation,
    OrganisationOperatesIn,
    TrendPoint,
)

pytestmark = pytest.mark.integration


async def test_data_tables_exist() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(select(IndicatorValue.place_id).limit(0))
        await conn.execute(select(TrendPoint.place_id).limit(0))
        await conn.execute(select(Organisation.id).limit(0))
        await conn.execute(select(OrganisationOperatesIn.organisation_id).limit(0))
        await conn.execute(select(GrantRecord.id).limit(0))
        await conn.execute(select(LoaderRun.id).limit(0))


async def test_indicator_value_pk_columns_present() -> None:
    pk_cols = {c.name for c in IndicatorValue.__table__.primary_key.columns}
    assert pk_cols == {"place_id", "indicator_key", "period"}

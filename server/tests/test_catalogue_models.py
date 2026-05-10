import pytest
from sqlalchemy import select

from soundings.db.engine import get_engine
from soundings.db.models.catalogue import Indicator, Source

pytestmark = pytest.mark.integration


async def test_source_table_exists() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            select(Source.id, Source.label, Source.mode, Source.licence).limit(0)
        )
        assert tuple(result.keys()) == ("id", "label", "mode", "licence")


async def test_indicator_table_exists() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            select(
                Indicator.key, Indicator.unit, Indicator.source_id, Indicator.available_at
            ).limit(0)
        )
        assert tuple(result.keys()) == ("key", "unit", "source_id", "available_at")

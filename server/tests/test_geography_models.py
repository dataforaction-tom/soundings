import pytest
from sqlalchemy import select

from soundings.db.engine import get_engine
from soundings.db.models.geography import Place

pytestmark = pytest.mark.integration


async def test_place_table_exists_with_required_columns() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(select(Place.id, Place.type, Place.code, Place.name).limit(0))
        assert tuple(result.keys()) == ("id", "type", "code", "name")

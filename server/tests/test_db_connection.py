import pytest
from sqlalchemy import text

from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def test_can_connect_and_query_postgis_version() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT postgis_version()"))
        version = result.scalar_one()
        assert version is not None
        assert "POSTGIS" in version.upper() or "USE_GEOS" in version.upper()

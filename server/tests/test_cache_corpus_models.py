import pytest
from sqlalchemy import select, text

from soundings.db.engine import get_engine
from soundings.db.models.cache import SourceCache
from soundings.db.models.corpus import QuestionRecord, RawRecord

pytestmark = pytest.mark.integration


async def test_cache_and_corpus_tables_exist() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(select(SourceCache.source_id, SourceCache.cache_key).limit(0))
        await conn.execute(select(QuestionRecord.id, QuestionRecord.tool_called).limit(0))
        await conn.execute(select(RawRecord.id).limit(0))


async def test_sanitiser_role_exists() -> None:
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = 'soundings_sanitiser'")
        )
        assert result.scalar_one_or_none() == 1

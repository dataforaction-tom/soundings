from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from soundings.adapters.source_ref_factory import SourceRefFactory
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _ensure_source(source_id: str) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO catalogue.source "
                "(id, label, publisher, publisher_url, dataset_url, licence, mode, rate_limit) "
                "VALUES (:id, :label, :pub, :pub_url, :ds_url, :lic, 'loader', '{}'::jsonb) "
                "ON CONFLICT (id) DO UPDATE SET label = EXCLUDED.label"
            ),
            {
                "id": source_id,
                "label": "Test Label",
                "pub": "Test Publisher",
                "pub_url": "https://example.invalid/",
                "ds_url": "https://example.invalid/data",
                "lic": "OGL-UK-3.0",
            },
        )


async def test_source_ref_factory_builds_from_catalogue_row() -> None:
    engine = get_engine()
    await _ensure_source("test.factory.source")

    factory = SourceRefFactory(engine)
    now = datetime.now(tz=UTC)
    ref = await factory.build("test.factory.source", retrieved_at=now, cache_status="cached")
    assert ref.source_id == "test.factory.source"
    assert ref.source_label == "Test Label"
    assert ref.publisher == "Test Publisher"
    assert ref.licence == "OGL-UK-3.0"
    assert ref.cache_status == "cached"
    assert ref.retrieved_at == now


async def test_source_ref_factory_returns_none_for_unknown_source() -> None:
    engine = get_engine()
    factory = SourceRefFactory(engine)
    ref = await factory.build(
        "test.unknown.never.registered",
        retrieved_at=datetime.now(tz=UTC),
        cache_status="live",
    )
    assert ref is None

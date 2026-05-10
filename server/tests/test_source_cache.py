from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from soundings.cache.source_cache import SourceCacheStore
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _ensure_source(source_id: str) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM cache.source_cache WHERE source_id = :s"), {"s": source_id}
        )
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, licence, mode, rate_limit) "
                "VALUES (:id, 'test', 'test', 'OGL', 'passthrough', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": source_id},
        )


async def test_put_then_get_within_ttl_returns_payload() -> None:
    engine = get_engine()
    await _ensure_source("test.cache.fresh")
    store = SourceCacheStore(engine)
    await store.put("test.cache.fresh", "TS18 1AB", {"hello": "world"}, ttl=timedelta(hours=1))
    got = await store.get("test.cache.fresh", "TS18 1AB")
    assert got == {"hello": "world"}


async def test_put_then_get_after_ttl_returns_none() -> None:
    engine = get_engine()
    await _ensure_source("test.cache.expired")
    store = SourceCacheStore(engine)
    # Synthesise an already-expired row.
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO cache.source_cache "
                "(source_id, cache_key, payload, retrieved_at, expires_at) "
                "VALUES ('test.cache.expired', 'k', CAST(:payload AS jsonb), :ret, :exp)"
            ),
            {
                "payload": '{"x": 1}',
                "ret": now - timedelta(hours=2),
                "exp": now - timedelta(hours=1),
            },
        )
    got = await store.get("test.cache.expired", "k")
    assert got is None


async def test_delete_expired_removes_stale_rows() -> None:
    engine = get_engine()
    await _ensure_source("test.cache.cleanup")
    store = SourceCacheStore(engine)
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM cache.source_cache WHERE source_id = 'test.cache.cleanup'")
        )
        await conn.execute(
            text(
                "INSERT INTO cache.source_cache "
                "(source_id, cache_key, payload, retrieved_at, expires_at) VALUES "
                "('test.cache.cleanup', 'old', '{}'::jsonb, :ret, :exp_old), "
                "('test.cache.cleanup', 'new', '{}'::jsonb, :ret, :exp_new)"
            ),
            {
                "ret": now - timedelta(hours=2),
                "exp_old": now - timedelta(hours=1),
                "exp_new": now + timedelta(hours=1),
            },
        )
    n_deleted = await store.delete_expired()
    assert n_deleted >= 1
    async with engine.connect() as conn:
        keys = (
            await conn.execute(
                text(
                    "SELECT cache_key FROM cache.source_cache "
                    "WHERE source_id = 'test.cache.cleanup'"
                )
            )
        ).all()
    assert {r.cache_key for r in keys} == {"new"}

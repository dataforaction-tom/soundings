"""TTL-keyed cache for passthrough adapter responses.

Keyed by `(source_id, cache_key)` and stamped with retrieved_at + expires_at.
Reads expired rows as `None` so callers can re-fetch upstream.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.db.models.cache import SourceCache


class SourceCacheStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, source_id: str, cache_key: str) -> Any | None:
        now = datetime.now(tz=UTC)
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(SourceCache.payload, SourceCache.expires_at).where(
                    SourceCache.source_id == source_id,
                    SourceCache.cache_key == cache_key,
                )
            )
            row = result.first()
        if row is None or row.expires_at <= now:
            return None
        return row.payload

    async def put(
        self,
        source_id: str,
        cache_key: str,
        payload: Any,
        *,
        ttl: timedelta,
    ) -> None:
        now = datetime.now(tz=UTC)
        expires = now + ttl
        async with self._engine.begin() as conn:
            stmt = insert(SourceCache).values(
                source_id=source_id,
                cache_key=cache_key,
                payload=payload,
                retrieved_at=now,
                expires_at=expires,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[SourceCache.source_id, SourceCache.cache_key],
                set_={
                    "payload": stmt.excluded.payload,
                    "retrieved_at": stmt.excluded.retrieved_at,
                    "expires_at": stmt.excluded.expires_at,
                },
            )
            await conn.execute(stmt)

    async def delete_expired(self) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM cache.source_cache WHERE expires_at <= now()")
            )
        return result.rowcount

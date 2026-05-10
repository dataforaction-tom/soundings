"""Base class for passthrough-mode adapters.

Passthrough adapters wrap an upstream HTTP API. Each call hits the cache
first, falls through to upstream on miss/stale, then writes the fresh
payload back into the cache. Subclasses implement `_call_upstream` and
`_materialise`.
"""

from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

import httpx
from aiolimiter import AsyncLimiter
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.cache.source_cache import SourceCacheStore


class PassthroughAdapter(ABC):
    source_id: str
    mode = "passthrough"

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        ttl: timedelta,
        rate_per_second: float = 4.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._cache = SourceCacheStore(engine)
        self._ttl = ttl
        self._limiter = AsyncLimiter(max_rate=rate_per_second, time_period=1)
        self._client = http_client

    async def _fetch_cached(self, cache_key: str) -> Any | None:
        cached = await self._cache.get(self.source_id, cache_key)
        if cached is not None:
            return cached

        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            try:
                payload = await self._call_upstream(client, cache_key)
            finally:
                if self._client is None:
                    await client.aclose()

        if payload is not None:
            await self._cache.put(self.source_id, cache_key, payload, ttl=self._ttl)
        return payload

    @abstractmethod
    async def _call_upstream(
        self, client: httpx.AsyncClient, cache_key: str
    ) -> Any | None:
        """Hit the upstream API. Return the JSON payload to cache, or None
        if the response is a known-empty result (404)."""
        ...

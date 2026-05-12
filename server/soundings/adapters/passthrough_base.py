"""Base class for passthrough-mode adapters.

Passthrough adapters wrap an upstream HTTP API. Each `fetch_indicator`
hits the cache first, falls through to upstream on miss/stale, then writes
the fresh payload back into the cache. Subclasses implement `_call_upstream`
and `_materialise`.
"""

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from aiolimiter import AsyncLimiter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.source_ref_factory import SourceRefFactory
from soundings.cache.source_cache import SourceCacheStore
from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.organisation import OrganisationRef
from soundings.contracts.source_ref import CacheStatus, SourceRef
from soundings.contracts.trend import Trend

_log = logging.getLogger(__name__)


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
        self._engine = engine
        self._cache = SourceCacheStore(engine)
        self._source_ref_factory = SourceRefFactory(engine)
        self._ttl = ttl
        self._limiter = AsyncLimiter(max_rate=rate_per_second, time_period=1)
        self._client = http_client

    @abstractmethod
    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any | None:
        """Hit the upstream API. Return the JSON payload to cache, or None
        if the response is a known-empty result (404)."""
        ...

    def _materialise(
        self,
        payload: Any,
        indicator_key: str,
        place_id: str,
        period: str | None,
        source_ref: SourceRef,
    ) -> IndicatorValue | None:
        """Map a cached/fresh payload into an IndicatorValue with the supplied
        SourceRef baked in. Override in subclasses that publish indicators;
        adapters that only feed the geography spine (e.g. postcodes.io) can
        leave the default which refuses to participate in `fetch_indicator`.
        """
        raise NotImplementedError(f"{type(self).__name__} does not publish indicator values")

    @staticmethod
    def _cache_key(indicator_key: str, place_id: str, period: str | None) -> str:
        return f"{indicator_key}|{place_id}|{period or 'latest'}"

    async def fetch_indicator(
        self,
        indicator_key: str,
        place_id: str,
        period: str | None,
    ) -> IndicatorValue | None:
        cache_key = self._cache_key(indicator_key, place_id, period)
        payload, status = await self._fetch_with_status(cache_key)
        if payload is None:
            return None
        source_ref = await self._build_source_ref(
            retrieved_at=datetime.now(tz=UTC), cache_status=status
        )
        return self._materialise(payload, indicator_key, place_id, period, source_ref)

    # ----- trend support (Phase 3) -----

    async def _call_upstream_trend(
        self,
        client: httpx.AsyncClient,
        cache_key: str,
        indicator_key: str,
        place_id: str,
        period_from: str | None,
        period_to: str | None,
    ) -> Any | None:
        """Subclasses that publish time series override this.

        Default refuses, mirroring _materialise's stance: adapters that
        don't publish trends inherit a NotImplementedError on call rather
        than silently returning an empty series.
        """
        del client, cache_key, indicator_key, place_id, period_from, period_to
        raise NotImplementedError(f"{type(self).__name__} does not publish time series")

    def _materialise_trend(
        self,
        payload: Any,
        indicator_key: str,
        place_id: str,
        source_ref: SourceRef,
    ) -> Trend:
        raise NotImplementedError(f"{type(self).__name__} does not publish time series")

    @staticmethod
    def _trend_cache_key(
        indicator_key: str,
        place_id: str,
        period_from: str | None,
        period_to: str | None,
    ) -> str:
        return f"{indicator_key}|{place_id}|trend|{period_from or 'open'}-{period_to or 'open'}"

    async def fetch_trend(
        self,
        indicator_key: str,
        place_id: str,
        period_from: str | None = None,
        period_to: str | None = None,
    ) -> Trend | None:
        cache_key = self._trend_cache_key(indicator_key, place_id, period_from, period_to)
        payload, status = await self._fetch_trend_with_status(
            cache_key, indicator_key, place_id, period_from, period_to
        )
        if payload is None:
            return None
        source_ref = await self._build_source_ref(
            retrieved_at=datetime.now(tz=UTC), cache_status=status
        )
        return self._materialise_trend(payload, indicator_key, place_id, source_ref)

    async def _fetch_trend_with_status(
        self,
        cache_key: str,
        indicator_key: str,
        place_id: str,
        period_from: str | None,
        period_to: str | None,
    ) -> tuple[Any | None, CacheStatus]:
        cached = await self._cache.get(self.source_id, cache_key)
        if cached is not None:
            return cached, "cached"

        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            try:
                payload = await self._call_upstream_trend(
                    client, cache_key, indicator_key, place_id, period_from, period_to
                )
            finally:
                if self._client is None:
                    await client.aclose()

        if payload is not None:
            await self._cache.put(self.source_id, cache_key, payload, ttl=self._ttl)
            return payload, "live"
        return None, "live"

    # ----- Phase 4: organisations + cache pre-warming -----

    async def fetch_organisations(
        self,
        place_id: str,
        filters: list[str] | None = None,
        limit: int = 50,
    ) -> list[OrganisationRef]:
        """Return organisations associated with a place.

        Default returns []. Adapters that publish organisational data
        (Phase 4: charity_commission, find_that_charity) override this.
        `filters` is a free-form list of activity / classification
        tags; adapters that don't apply them ignore the param.
        """
        del place_id, filters, limit
        return []

    async def pre_warm_for_places(self, place_ids: list[str]) -> None:
        """Pre-populate the cache for a set of places.

        Default is a no-op. Adapters that publish slow-changing
        aggregates (Phase 4: civil_society.* counts via CC, 360G grant
        sums) override this so the pre_warmer daemon can keep
        user-facing reads on a warm cache.
        """
        del place_ids

    async def safe_pre_warm(self, place_ids: list[str]) -> None:
        """Best-effort wrapper around `pre_warm_for_places`.

        The pre_warmer daemon calls this so a single misbehaving
        adapter can't poison the loop. Exceptions are logged and
        swallowed; the daemon moves on to the next adapter.
        """
        try:
            await self.pre_warm_for_places(place_ids)
        except Exception:
            _log.exception(
                "pre_warm_for_places failed for source_id=%s (%d places)",
                self.source_id,
                len(place_ids),
            )

    async def list_available_indicators(self) -> list[str]:
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT key FROM catalogue.indicator WHERE source_id = :sid"),
                    {"sid": self.source_id},
                )
            ).all()
        return [r.key for r in rows]

    async def _fetch_cached(self, cache_key: str) -> Any | None:
        """Back-compat shim for adapters that don't yet use _fetch_with_status."""
        payload, _status = await self._fetch_with_status(cache_key)
        return payload

    async def _fetch_with_status(self, cache_key: str) -> tuple[Any | None, CacheStatus]:
        cached = await self._cache.get(self.source_id, cache_key)
        if cached is not None:
            return cached, "cached"

        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            try:
                payload = await self._call_upstream(client, cache_key)
            finally:
                if self._client is None:
                    await client.aclose()

        if payload is not None:
            await self._cache.put(self.source_id, cache_key, payload, ttl=self._ttl)
            return payload, "live"
        return None, "live"

    async def _build_source_ref(
        self, *, retrieved_at: datetime, cache_status: CacheStatus
    ) -> SourceRef:
        ref = await self._source_ref_factory.build(
            self.source_id, retrieved_at=retrieved_at, cache_status=cache_status
        )
        if ref is None:
            return SourceRef(
                source_id=self.source_id,
                source_label=self.source_id,
                publisher="",
                licence="",
                retrieved_at=retrieved_at,
                cache_status=cache_status,
            )
        return ref

    def get_source_ref(
        self,
        *,
        retrieved_at: datetime,
        cache_status: CacheStatus,
    ) -> SourceRef:
        # Synchronous variant — useful when caller already has source metadata.
        return SourceRef(
            source_id=self.source_id,
            source_label=self.source_id,
            publisher="",
            licence="",
            retrieved_at=retrieved_at,
            cache_status=cache_status,
        )

"""OhidFingertipsAdapter — passthrough over the Fingertips public API.

Fingertips' `/all_data/json/by_indicator_id` returns every area of a
given child_area_type for one indicator. We cache the whole payload
per indicator (24h TTL) and filter to the requested place_id at
request time. That keeps the upstream call count one-per-indicator
regardless of how many places the orchestrator is asking about in a
single tool call.

Sex / Age filtering happens client-side because Fingertips doesn't
accept those as query params on `all_data` endpoints.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.ohid_fingertips.client import FingertipsClient
from soundings.adapters.ohid_fingertips.mapping import (
    FingertipsMapping,
    load_fingertips_mapping,
)
from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.source_ref import SourceRef
from soundings.contracts.trend import Trend, TrendPoint

SOURCE_ID = "ohid.fingertips"


class OhidFingertipsAdapter(PassthroughAdapter):
    source_id = SOURCE_ID

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        ttl: timedelta = timedelta(hours=24),
        fingertips_client: FingertipsClient | None = None,
        mapping_path: Path | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(engine, ttl=ttl, http_client=http_client)
        self._fingertips = fingertips_client or FingertipsClient(http_client=http_client)
        self._mapping = {m.indicator_key: m for m in load_fingertips_mapping(mapping_path)}

    async def fetch_indicator(
        self,
        indicator_key: str,
        place_id: str,
        period: str | None,
    ) -> IndicatorValue | None:
        mapping = self._mapping.get(indicator_key)
        if mapping is None:
            return None
        place_code = _strip_type_prefix(place_id)
        rows = await self._fetch_indicator_rows(indicator_key, mapping)
        if not rows:
            return None
        matched = _filter_rows(rows, place_code, mapping, period=period)
        if not matched:
            return None
        latest = max(matched, key=lambda r: _row_period(r))
        source_ref = await self._build_source_ref(
            retrieved_at=datetime.now(tz=UTC), cache_status="cached"
        )
        return IndicatorValue(
            place_id=place_id,
            indicator=indicator_key,
            value=_row_value(latest),
            unit=mapping.unit,
            period=str(_row_period(latest)),
            source=source_ref,
            caveats=mapping.caveats,
            confidence="official",
        )

    async def fetch_trend(
        self,
        indicator_key: str,
        place_id: str,
        period_from: str | None = None,
        period_to: str | None = None,
    ) -> Trend | None:
        mapping = self._mapping.get(indicator_key)
        if mapping is None:
            return None
        place_code = _strip_type_prefix(place_id)
        rows = await self._fetch_indicator_rows(indicator_key, mapping)
        if not rows:
            return None
        matched = _filter_rows(rows, place_code, mapping, period=None)
        # Reduce to one point per period; sort ascending.
        by_period: dict[str, dict[str, Any]] = {}
        for row in matched:
            key = str(_row_period(row))
            by_period[key] = row
        points = [
            TrendPoint(period=p, value=_row_value(by_period[p]))
            for p in sorted(by_period)
            if _within_window(p, period_from, period_to)
        ]
        if not points:
            return None
        source_ref = await self._build_source_ref(
            retrieved_at=datetime.now(tz=UTC), cache_status="cached"
        )
        return Trend(
            place_id=place_id,
            indicator=indicator_key,
            unit=mapping.unit,
            points=points,
            source=source_ref,
        )

    async def _fetch_indicator_rows(
        self, indicator_key: str, mapping: FingertipsMapping
    ) -> list[dict[str, Any]]:
        """Cache the entire indicator payload under one key per upstream id.

        Multiple soundings indicator_keys can share the same Fingertips
        indicator_id (e.g. life_expectancy.female and .male both use 90366
        and differ only by the Sex filter). Cache by upstream id so they
        share the network call.
        """
        del indicator_key
        cache_key = f"fingertips:indicator:{mapping.indicator_id}:{mapping.child_area_type_id}"
        cached = await self._cache.get(self.source_id, cache_key)
        if cached is not None and isinstance(cached, list):
            return cached
        rows = await self._fingertips.get_indicator_data(
            indicator_id=mapping.indicator_id,
            child_area_type_id=mapping.child_area_type_id,
            parent_area_type_id=mapping.parent_area_type_id,
        )
        if rows:
            await self._cache.put(self.source_id, cache_key, rows, ttl=self._ttl)
        return rows

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any:
        # Required by PassthroughAdapter ABC; we override fetch_indicator
        # entirely so the base-class path doesn't fire.
        del client, cache_key
        raise NotImplementedError("OhidFingertipsAdapter routes via fetch_indicator override")

    def _build_source_ref_sync(self, *, retrieved_at: datetime, cache_status: str) -> SourceRef:
        return self.get_source_ref(retrieved_at=retrieved_at, cache_status=cache_status)  # type: ignore[arg-type]


def _strip_type_prefix(place_id: str) -> str:
    # "ltla24:E06000004" → "E06000004"
    if ":" in place_id:
        return place_id.split(":", 1)[1]
    return place_id


def _row_value(row: dict[str, Any]) -> float | None:
    raw = row.get("Value")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _row_period(row: dict[str, Any]) -> str:
    # Prefer the TimePeriod string ("2020 - 22"); fall back to Year.
    if (tp := row.get("TimePeriod")) is not None:
        return str(tp)
    if (yr := row.get("Year")) is not None:
        return str(yr)
    return ""


def _filter_rows(
    rows: list[dict[str, Any]],
    place_code: str,
    mapping: FingertipsMapping,
    *,
    period: str | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("AreaCode") != place_code:
            continue
        if mapping.sex is not None and row.get("Sex") != mapping.sex:
            continue
        if mapping.age is not None and row.get("Age") != mapping.age:
            continue
        if period is not None and _row_period(row) != period:
            continue
        out.append(row)
    return out


def _within_window(period: str, frm: str | None, to: str | None) -> bool:
    if frm is not None and period < frm:
        return False
    if to is not None and period > to:
        return False
    return True

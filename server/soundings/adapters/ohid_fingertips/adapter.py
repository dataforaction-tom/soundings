"""OhidFingertipsAdapter — passthrough over the Fingertips public API.

Fingertips returns a whole (profile × group × area_type) page in one
call. We cache that page (24h TTL) per (profile_id, group_id,
area_type_id) and match individual soundings indicators against it
by (indicator_id, sex_id, age_id). Multiple soundings keys backed by
the same upstream page share the one network call.

Period strings are taken straight from Fingertips (`"2023 - 25"`) so
they line up across IndicatorCard rendering on the UI.
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
        records = await self._fetch_group_page(mapping)
        rows = _filter_rows_for_indicator(records, mapping, place_code, period=period)
        if not rows:
            return None
        latest = max(rows, key=_period_string)
        source_ref = await self._build_source_ref(
            retrieved_at=datetime.now(tz=UTC), cache_status="cached"
        )
        return IndicatorValue(
            place_id=place_id,
            indicator=indicator_key,
            value=_row_value(latest),
            unit=mapping.unit,
            period=_period_string(latest),
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
        records = await self._fetch_group_page(mapping)
        rows = _filter_rows_for_indicator(records, mapping, place_code, period=None)
        if not rows:
            return None
        by_period: dict[str, dict[str, Any]] = {}
        for row in rows:
            by_period[_period_string(row)] = row
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

    async def _fetch_group_page(self, mapping: FingertipsMapping) -> list[dict[str, Any]]:
        """One cache entry per (profile_id, group_id, area_type_id, parent).

        All indicators in the same Fingertips group share the response,
        so multiple soundings keys collapse to one network call.
        """
        cache_key = (
            f"fingertips:group:{mapping.profile_id}:{mapping.group_id}"
            f":{mapping.child_area_type_id}:{mapping.parent_area_code}"
        )
        cached = await self._cache.get(self.source_id, cache_key)
        if cached is not None and isinstance(cached, list):
            return cached
        records = await self._fingertips.get_group_data(
            profile_id=mapping.profile_id,
            group_id=mapping.group_id,
            area_type_id=mapping.child_area_type_id,
            parent_area_code=mapping.parent_area_code,
        )
        if records:
            await self._cache.put(self.source_id, cache_key, records, ttl=self._ttl)
        return records

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any:
        del client, cache_key
        raise NotImplementedError("OhidFingertipsAdapter routes via fetch_indicator override")


def _strip_type_prefix(place_id: str) -> str:
    if ":" in place_id:
        return place_id.split(":", 1)[1]
    return place_id


def _row_value(row: dict[str, Any]) -> float | None:
    raw = row.get("Val")
    if raw is None or raw == -1:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _period_string(row: dict[str, Any]) -> str:
    """Fingertips records use Year + YearRange (1 = single year, 3 = 3-year)."""
    year = row.get("Year")
    year_range = row.get("YearRange") or 1
    if year is None:
        return ""
    if year_range == 1:
        return str(year)
    start = year - year_range + 1
    return f"{start} - {str(year)[-2:]}"


def _filter_rows_for_indicator(
    records: list[dict[str, Any]],
    mapping: FingertipsMapping,
    place_code: str,
    *,
    period: str | None,
) -> list[dict[str, Any]]:
    """Match the (indicator_id, sex_id, age_id) grouping, then filter Data."""
    matched: list[dict[str, Any]] = []
    for record in records:
        sex = record.get("Sex") or {}
        age = record.get("Age") or {}
        if sex.get("Id") != mapping.sex_id:
            continue
        if age.get("Id") != mapping.age_id:
            continue
        grouping_entries = record.get("Grouping") or []
        if not any(g.get("IndicatorId") == mapping.indicator_id for g in grouping_entries):
            continue
        for row in record.get("Data") or []:
            if row.get("AreaCode") != place_code:
                continue
            if row.get("IndicatorId") != mapping.indicator_id:
                continue
            if period is not None and _period_string(row) != period:
                continue
            matched.append(row)
    return matched


def _within_window(period: str, frm: str | None, to: str | None) -> bool:
    if frm is not None and period < frm:
        return False
    if to is not None and period > to:
        return False
    return True

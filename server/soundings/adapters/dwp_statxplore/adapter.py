"""DwpStatXploreAdapter — passthrough over the Stat-Xplore cube API.

For each indicator, the adapter queries the cube once per (place_id,
database+measure) — fetching all available periods — and caches the
result. `fetch_indicator` picks the latest period; `fetch_trend`
slices to the requested window.

Stat-Xplore response shape (one cube, one place, N dates):

    {
      "cubes": {
        "<measure-id>": {"values": [[123, 145, 167]]}
      },
      "fields": [
        {"items": [{"labels": ["E06000004", "Stockton-on-Tees"]}]},
        {"items": [
          {"labels": ["202401"]}, {"labels": ["202402"]}, ...
        ]}
      ]
    }

The geography dimension is queried with a single recoded value
(the requested place), so `fields[0]` has one entry. `fields[1]` is
the date axis aligned with the inner values array.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.dwp_statxplore.client import StatXploreClient
from soundings.adapters.dwp_statxplore.mapping import (
    StatXploreMapping,
    load_statxplore_mapping,
)
from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.trend import Trend, TrendPoint

SOURCE_ID = "dwp.statxplore"


class DwpStatXploreAdapter(PassthroughAdapter):
    source_id = SOURCE_ID

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        ttl: timedelta = timedelta(hours=24),
        statxplore_client: StatXploreClient | None = None,
        mapping_path: Path | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(engine, ttl=ttl, http_client=http_client)
        self._statxplore = statxplore_client or StatXploreClient(http_client=http_client)
        self._mapping = {m.indicator_key: m for m in load_statxplore_mapping(mapping_path)}

    async def fetch_indicator(
        self,
        indicator_key: str,
        place_id: str,
        period: str | None,
    ) -> IndicatorValue | None:
        mapping = self._mapping.get(indicator_key)
        if mapping is None:
            return None
        points = await self._fetch_points(mapping, place_id)
        if not points:
            return None
        if period is not None:
            matched = [p for p in points if p["period"] == period]
            if not matched:
                return None
            chosen = matched[0]
        else:
            chosen = max(points, key=lambda p: p["period"])
        source_ref = await self._build_source_ref(
            retrieved_at=datetime.now(tz=UTC), cache_status="cached"
        )
        return IndicatorValue(
            place_id=place_id,
            indicator=indicator_key,
            value=chosen["value"],
            unit=mapping.unit,
            period=chosen["period"],
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
        points = await self._fetch_points(mapping, place_id)
        in_window = [
            TrendPoint(period=p["period"], value=p["value"])
            for p in sorted(points, key=lambda r: r["period"])
            if _within_window(p["period"], period_from, period_to)
        ]
        if not in_window:
            return None
        source_ref = await self._build_source_ref(
            retrieved_at=datetime.now(tz=UTC), cache_status="cached"
        )
        return Trend(
            place_id=place_id,
            indicator=indicator_key,
            unit=mapping.unit,
            points=in_window,
            source=source_ref,
        )

    async def _fetch_points(
        self, mapping: StatXploreMapping, place_id: str
    ) -> list[dict[str, Any]]:
        place_code = _strip_type_prefix(place_id)
        cache_key = f"statxplore:{mapping.database}:{mapping.measures[0]}:{place_code}"
        cached = await self._cache.get(self.source_id, cache_key)
        if cached is not None and isinstance(cached, list):
            return cached

        recodes = {
            mapping.geography_dim: {
                "map": [[mapping.geography_value_template.format(place_code=place_code)]],
                "total": False,
            }
        }
        payload = await self._statxplore.get_table(
            database=mapping.database,
            measures=mapping.measures,
            dimensions=[[mapping.geography_dim], [mapping.date_dim]],
            recodes=recodes,
        )
        points = _materialise_points(payload, mapping)
        if points:
            await self._cache.put(self.source_id, cache_key, points, ttl=self._ttl)
        return points

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any:
        del client, cache_key
        raise NotImplementedError("DwpStatXploreAdapter routes via fetch_indicator override")


def _strip_type_prefix(place_id: str) -> str:
    if ":" in place_id:
        return place_id.split(":", 1)[1]
    return place_id


def _materialise_points(
    payload: dict[str, Any], mapping: StatXploreMapping
) -> list[dict[str, Any]]:
    """Walk the (geography × date × measure) cube response.

    We expect exactly one geography (the recoded place), so the values
    array is shape [[v1, v2, ...]] where index i in the inner array
    aligns with fields[1] (date axis).
    """
    measure_id = mapping.measures[0]
    cube = (payload.get("cubes") or {}).get(measure_id) or {}
    values = cube.get("values") or []
    if not values:
        return []
    inner = values[0] if isinstance(values[0], list) else values
    fields = payload.get("fields") or []
    if len(fields) < 2:
        return []
    date_items = (fields[1].get("items") or []) if isinstance(fields[1], dict) else []
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(date_items):
        if idx >= len(inner):
            break
        labels = item.get("labels") or []
        if not labels:
            continue
        period = str(labels[0])
        raw = inner[idx]
        value = float(raw) if isinstance(raw, (int, float)) else None
        out.append({"period": period, "value": value})
    return out


def _within_window(period: str, frm: str | None, to: str | None) -> bool:
    if frm is not None and period < frm:
        return False
    if to is not None and period > to:
        return False
    return True

"""OsmOverpassAdapter — amenity counts from OpenStreetMap.

For each place, take the bounding box of the place polygon, query the
Overpass API for OSM elements matching the indicator's tag(s) within that
box, and return the total count. Indicators with multiple tag sets
(e.g. GP practices, sports facilities, food banks) query each tag and
sum the results.

This is count data from a volunteered geographic information project — not
a census or official register. Every returned `IndicatorValue` carries the
methodology caveat below; the adapter test asserts the caveat verbatim so
a refactor removing it fails CI.

Indicator → OSM tag mapping is stable enough to live as a Python constant.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.osm_overpass.client import OsmOverpassClient
from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.contracts.indicator_value import IndicatorValue

SOURCE_ID = "osm_overpass"
METHODOLOGY_CAVEAT = (
    "Count from OpenStreetMap data via Overpass API. Coverage varies by area "
    "— some amenities may be missing or miscategorised."
)

INDICATOR_TAGS: dict[str, list[dict[str, str]]] = {
    "infrastructure.schools_count": [{"amenity": "school"}],
    "infrastructure.hospitals_count": [{"amenity": "hospital"}],
    "infrastructure.libraries_count": [{"amenity": "library"}],
    "infrastructure.community_centres_count": [{"amenity": "community_centre"}],
    "infrastructure.parks_count": [{"leisure": "park"}],
    "infrastructure.pharmacies_count": [{"amenity": "pharmacy"}],
    "infrastructure.gp_practices_count": [{"amenity": "clinic"}, {"healthcare": "clinic"}],
    "infrastructure.sports_facilities_count": [
        {"leisure": "sports_centre"},
        {"leisure": "pitch"},
        {"leisure": "sports_hub"},
    ],
    "infrastructure.food_banks_count": [
        {"amenity": "food_bank"},
        {"social_facility": "food_bank"},
    ],
}


class OsmOverpassAdapter(PassthroughAdapter):
    source_id = SOURCE_ID

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        ttl: timedelta = timedelta(hours=720),
        overpass_client: OsmOverpassClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(engine, ttl=ttl, rate_per_second=2.0, http_client=http_client)
        self._overpass = overpass_client or OsmOverpassClient(http_client=http_client)

    async def fetch_indicator(
        self,
        indicator_key: str,
        place_id: str,
        period: str | None,
    ) -> IndicatorValue | None:
        tags = INDICATOR_TAGS.get(indicator_key)
        if tags is None:
            return None

        cache_key = f"osm:{indicator_key}:{place_id}"
        cached = await self._cache.get(self.source_id, cache_key)
        if cached is not None and isinstance(cached, dict):
            total_count = int(cached.get("total_count", 0))
            period_used = str(cached.get("period", ""))
        else:
            bbox = await self._get_bbox(place_id)
            if bbox is None:
                return None

            total_count = 0
            for tag_dict in tags:
                for k, v in tag_dict.items():
                    count = await self._overpass.count_by_tag(k, v, bbox)
                    total_count += count

            period_used = period or datetime.now(tz=UTC).strftime("%Y-%m")
            await self._cache.put(
                self.source_id,
                cache_key,
                {"total_count": total_count, "period": period_used},
                ttl=self._ttl,
            )

        source_ref = await self._build_source_ref(
            retrieved_at=datetime.now(tz=UTC), cache_status="cached"
        )
        return IndicatorValue(
            place_id=place_id,
            indicator=indicator_key,
            value=float(total_count),
            unit="count",
            period=period_used,
            source=source_ref,
            caveats=[METHODOLOGY_CAVEAT],
            confidence="official",
        )

    async def amenity_locations(self, indicator_key: str, place_id: str) -> dict | None:
        """GeoJSON FeatureCollection of amenity point locations for one
        indicator within a place. Cached under `osmgeo:{key}:{place_id}`.

        Returns None for a non-amenity indicator; an empty FeatureCollection
        when the place has no geometry or no matching amenities. A transport
        failure propagates (not cached), like the count path.
        """
        tags = INDICATOR_TAGS.get(indicator_key)
        if tags is None:
            return None

        cache_key = f"osmgeo:{indicator_key}:{place_id}"
        cached = await self._cache.get(self.source_id, cache_key)
        if isinstance(cached, dict):
            return cached

        bbox = await self._get_bbox(place_id)
        if bbox is None:
            return {"type": "FeatureCollection", "features": []}

        seen: set[tuple[float, float]] = set()
        features: list[dict[str, Any]] = []
        for tag_dict in tags:
            for k, v in tag_dict.items():
                for pt in await self._overpass.locations_by_tag(k, v, bbox):
                    key = (round(pt["lat"], 6), round(pt["lng"], 6))
                    if key in seen:
                        continue
                    seen.add(key)
                    features.append(
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [pt["lng"], pt["lat"]]},
                            "properties": {"name": pt["name"], "layer": indicator_key},
                        }
                    )

        fc = {"type": "FeatureCollection", "features": features}
        await self._cache.put(self.source_id, cache_key, fc, ttl=self._ttl)
        return fc

    async def pre_warm_for_places(self, place_ids: list[str]) -> None:
        """Populate the amenity-count cache for every OSM indicator across the
        given places, out-of-band of the orchestrator's soft budget.

        County-wide and multi-tag Overpass counts can take longer than the
        orchestrator's per-call budget; a user-path fetch that overruns is
        cancelled before it can cache, so it would time out on every request.
        The pre_warmer daemon calls this on the source's refresh cadence so
        user reads always hit a warm cache. Per-(indicator, place) failures
        are logged and skipped — one bad lookup must not blank the warm pass.
        """
        import logging

        log = logging.getLogger(__name__)
        for place_id in place_ids:
            for indicator_key in INDICATOR_TAGS:
                try:
                    await self.fetch_indicator(indicator_key, place_id, None)
                except Exception:
                    log.exception(
                        "OSM pre_warm failed for indicator=%s place_id=%s",
                        indicator_key,
                        place_id,
                    )

    async def _get_bbox(self, place_id: str) -> tuple[float, float, float, float] | None:
        """Get bounding box (south, west, north, east) from PostGIS."""
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT ST_YMin(geom) AS min_lat, ST_XMin(geom) AS min_lng, "
                        "ST_YMax(geom) AS max_lat, ST_XMax(geom) AS max_lng "
                        "FROM geography.place WHERE id = :pid AND geom IS NOT NULL"
                    ),
                    {"pid": place_id},
                )
            ).first()
        if row is None or row.min_lat is None:
            return None
        return (
            float(row.min_lat),
            float(row.min_lng),
            float(row.max_lat),
            float(row.max_lng),
        )

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any | None:
        del client, cache_key
        raise NotImplementedError("OsmOverpassAdapter routes via fetch_indicator override")

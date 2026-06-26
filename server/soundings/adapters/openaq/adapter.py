"""OpenAqAdapter — IDW interpolation of nearby air-quality sensors.

For each place, take the geometric centroid of the place polygon, query
OpenAQ for monitoring stations within `SEARCH_RADIUS_M` (20 km), fetch the
latest measurement from each station's sensor matching the requested
parameter, and interpolate the readings onto the centroid using inverse
distance weighting (IDW).

This is point-sensor data interpolated to place level — not a
boundary-bounded measurement. Every returned `IndicatorValue` carries the
methodology caveat below; the adapter test asserts the caveat verbatim so a
refactor removing it fails CI.

Indicator → OpenAQ parameter name mapping is small and stable enough to
live as a Python constant.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.openaq.client import OpenAqClient
from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.contracts.indicator_value import IndicatorValue

SOURCE_ID = "openaq"
UNIT = "µg/m³"
SEARCH_RADIUS_M = 20000  # 20 km

METHODOLOGY_CAVEAT = (
    "Interpolated from nearby monitoring stations using inverse distance "
    "weighting. Actual local exposure may vary."
)

INDICATOR_PARAMS: dict[str, str] = {
    "environment.air_quality.pm25": "pm25",
    "environment.air_quality.pm10": "pm10",
    "environment.air_quality.no2": "no2",
    "environment.air_quality.o3": "o3",
    "environment.air_quality.so2": "so2",
}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points, in kilometres."""
    r = 6371.0088  # mean Earth radius in km
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) * math.sin(dp / 2) + math.cos(p1) * math.cos(p2) * math.sin(
        dl / 2
    ) * math.sin(dl / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


class OpenAqAdapter(PassthroughAdapter):
    source_id = SOURCE_ID

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        ttl: timedelta = timedelta(hours=1),
        openaq_client: OpenAqClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(engine, ttl=ttl, rate_per_second=4.0, http_client=http_client)
        self._openaq = openaq_client or OpenAqClient(http_client=http_client)

    async def fetch_indicator(
        self,
        indicator_key: str,
        place_id: str,
        period: str | None,
    ) -> IndicatorValue | None:
        param_name = INDICATOR_PARAMS.get(indicator_key)
        if param_name is None:
            return None

        cache_key = f"openaq:{param_name}:{place_id}"
        cached = await self._cache.get(self.source_id, cache_key)
        if cached is not None and isinstance(cached, dict):
            value = cached.get("value")
            period_used = str(cached.get("period", ""))
        else:
            value = await self._fetch_value(param_name, place_id)
            if value is None:
                return None
            period_used = period or datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:00:00Z")
            await self._cache.put(
                self.source_id,
                cache_key,
                {"value": value, "period": period_used},
                ttl=self._ttl,
            )

        source_ref = await self._build_source_ref(
            retrieved_at=datetime.now(tz=UTC), cache_status="cached"
        )
        return IndicatorValue(
            place_id=place_id,
            indicator=indicator_key,
            value=value,
            unit=UNIT,
            period=period_used,
            source=source_ref,
            caveats=[METHODOLOGY_CAVEAT],
            confidence="modelled",
        )

    async def _fetch_value(self, param_name: str, place_id: str) -> float | None:
        """Fetch nearby stations, pull latest readings for `param_name`,
        and interpolate onto the place centroid via IDW. Returns None if no
        usable readings are available."""
        centroid = await self._get_centroid(place_id)
        if centroid is None:
            return None
        lat, lng = centroid

        locations = await self._openaq.get_nearby_locations(lat, lng, SEARCH_RADIUS_M)
        if not locations:
            return None

        readings: list[tuple[float, float]] = []  # (distance_km, value)
        for loc in locations:
            coords = loc.get("coordinates", {})
            if not isinstance(coords, dict):
                continue
            loc_lat = coords.get("latitude")
            loc_lng = coords.get("longitude")
            if loc_lat is None or loc_lng is None:
                continue
            distance_km = haversine_km(lat, lng, float(loc_lat), float(loc_lng))

            for sensor in loc.get("sensors", []):
                if not isinstance(sensor, dict):
                    continue
                p = sensor.get("parameter", {})
                if not isinstance(p, dict) or p.get("name") != param_name:
                    continue
                sensor_id = sensor.get("id")
                if sensor_id is None:
                    continue
                measurement = await self._openaq.get_latest_measurement(int(sensor_id))
                if measurement is not None:
                    readings.append((distance_km, measurement))
                break  # one sensor per parameter per location

        if not readings:
            return None

        if len(readings) == 1:
            return readings[0][1]

        weighted = 0.0
        total_weight = 0.0
        eps = 1e-9  # floor so a station exactly at the centroid dominates
        for distance_km, val in readings:
            weight = 1.0 / (max(distance_km, eps) ** 2)
            weighted += val * weight
            total_weight += weight
        if total_weight > 0:
            return weighted / total_weight
        return readings[0][1]

    async def _get_centroid(self, place_id: str) -> tuple[float, float] | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT ST_Y(ST_Centroid(geom)) AS lat, "
                        "ST_X(ST_Centroid(geom)) AS lng "
                        "FROM geography.place "
                        "WHERE id = :pid AND geom IS NOT NULL"
                    ),
                    {"pid": place_id},
                )
            ).first()
        if row is None or row.lat is None or row.lng is None:
            return None
        return float(row.lat), float(row.lng)

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any | None:
        del client, cache_key
        raise NotImplementedError("OpenAqAdapter routes via fetch_indicator override")

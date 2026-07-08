"""OpenWeatherAdapter — modelled air quality at the place centroid.

For each place, take the polygon centroid and query the OpenWeather Air
Pollution API for that point, returning the requested pollutant's modelled
concentration (µg/m³). Unlike the OpenAQ adapter (which interpolates nearby
ground sensors via IDW), OpenWeather returns a single modelled value per
coordinate — so there is no sensor search or interpolation, just a centroid
lookup.

This is a modelled product (CAMS-based), not a boundary-bounded
measurement; every returned value carries the methodology caveat, and the
adapter test asserts it verbatim.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.openweather.client import OpenWeatherAirClient
from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.contracts.indicator_value import IndicatorValue

SOURCE_ID = "openweather"
UNIT = "µg/m³"

METHODOLOGY_CAVEAT = (
    "Modelled air pollution from the OpenWeather (CAMS-based) air-quality "
    "model, sampled at the area centroid. Actual local exposure may vary."
)

# Indicator key -> OpenWeather `components` field name.
INDICATOR_COMPONENTS: dict[str, str] = {
    "environment.air_quality.pm25": "pm2_5",
    "environment.air_quality.pm10": "pm10",
    "environment.air_quality.no2": "no2",
    "environment.air_quality.o3": "o3",
    "environment.air_quality.so2": "so2",
}


class OpenWeatherAdapter(PassthroughAdapter):
    source_id = SOURCE_ID

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        ttl: timedelta = timedelta(hours=1),
        owm_client: OpenWeatherAirClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(engine, ttl=ttl, rate_per_second=4.0, http_client=http_client)
        self._owm = owm_client or OpenWeatherAirClient(http_client=http_client)

    async def fetch_indicator(
        self,
        indicator_key: str,
        place_id: str,
        period: str | None,
    ) -> IndicatorValue | None:
        component = INDICATOR_COMPONENTS.get(indicator_key)
        if component is None:
            return None

        cache_key = f"openweather:{component}:{place_id}"
        cached = await self._cache.get(self.source_id, cache_key)
        if cached is not None and isinstance(cached, dict):
            value = cached.get("value")
            period_used = str(cached.get("period", ""))
        else:
            value = await self._fetch_value(component, place_id)
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

    async def _fetch_value(self, component: str, place_id: str) -> float | None:
        centroid = await self._get_centroid(place_id)
        if centroid is None:
            return None
        lat, lng = centroid
        components = await self._owm.get_components(lat, lng)
        if not components:
            return None
        raw = components.get(component)
        return float(raw) if raw is not None else None

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
        raise NotImplementedError("OpenWeatherAdapter routes via fetch_indicator override")

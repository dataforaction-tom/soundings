"""OpenWeather Air Pollution API client.

One call per place centroid returns modelled concentrations for all
pollutants (CO, NO, NO2, O3, SO2, PM2.5, PM10, NH3) in µg/m³. Requires
`OPENWEATHER_API_KEY` in the environment (free tier, 1000 calls/day). Free
signup at <https://openweathermap.org/api>.

Docs: https://openweathermap.org/api/air-pollution
"""

import os
from typing import Any

import httpx

BASE_URL = "https://api.openweathermap.org/data/2.5/air_pollution"


class OpenWeatherAirClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        api_key: str | None = None,
    ) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._explicit_api_key = api_key

    def _api_key(self) -> str | None:
        return self._explicit_api_key or os.environ.get("OPENWEATHER_API_KEY")

    async def get_components(self, lat: float, lng: float) -> dict[str, float] | None:
        """Return the pollutant `components` dict for the given point, or
        None if the API returns no data. Keys are OpenWeather component names
        (`no2`, `o3`, `so2`, `pm2_5`, `pm10`, ...) in µg/m³."""
        api_key = self._api_key()
        if not api_key:
            raise RuntimeError("OPENWEATHER_API_KEY is not set — cannot query OpenWeather")
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            response = await client.get(BASE_URL, params={"lat": lat, "lon": lng, "appid": api_key})
            response.raise_for_status()
            return _parse_components(response.json())
        finally:
            if self._owns_client:
                await client.aclose()


def _parse_components(payload: Any) -> dict[str, float] | None:
    """Extract the first reading's `components` dict from an air_pollution
    response. The API shape is `{"list": [{"components": {...}}]}`."""
    if not isinstance(payload, dict):
        return None
    items = payload.get("list")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    components = first.get("components")
    if not isinstance(components, dict):
        return None
    return {k: float(v) for k, v in components.items() if isinstance(v, int | float)}

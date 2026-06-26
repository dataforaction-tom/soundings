"""Async HTTP wrapper for the OpenAQ v3 public API.

Base: https://api.openaq.org/v3

Unauthenticated. Two endpoints are used:

    GET /v3/locations?coordinates=lat,lng&radius_meters=N
        → nearby monitoring stations with their sensor list.

    GET /v3/sensors/{sensor_id}/measurements?limit=1&order_by=datetime&sort=desc
        → the latest measurement for a single sensor.

The geographic semantics are radius-bounded point queries — `OpenAqAdapter`
interpolates the returned point readings onto a place centroid, so the
methodology caveat flowing from that lives in the adapter, not here.
"""

from typing import Any

import httpx
from aiolimiter import AsyncLimiter

OPENAQ_BASE = "https://api.openaq.org/v3"


class OpenAqClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        rate_per_second: float = 4.0,
    ) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._limiter = AsyncLimiter(max_rate=rate_per_second, time_period=1)

    async def get_nearby_locations(
        self,
        lat: float,
        lng: float,
        radius_meters: int = 20000,
    ) -> list[dict[str, Any]]:
        """GET /v3/locations?coordinates=lat,lng&radius_meters=N.

        Returns the `results` list (location dicts with id, name,
        coordinates, sensors). Empty list if no stations are found or
        the response shape is unexpected.
        """
        params: dict[str, str] = {
            "coordinates": f"{lat},{lng}",
            "radius_meters": str(radius_meters),
        }
        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=60.0)
            try:
                response = await client.get(f"{OPENAQ_BASE}/locations", params=params)
                response.raise_for_status()
                payload = response.json()
            finally:
                if self._owns_client:
                    await client.aclose()

        if not isinstance(payload, dict):
            return []
        results = payload.get("results")
        if not isinstance(results, list):
            return []
        return [r for r in results if isinstance(r, dict)]

    async def get_latest_measurement(self, sensor_id: int) -> float | None:
        """GET /v3/sensors/{sensor_id}/measurements?limit=1&order_by=datetime&sort=desc.

        Returns the latest `value` as a float, or None if no measurement
        is available or the response shape is unexpected.
        """
        params: dict[str, str] = {
            "limit": "1",
            "order_by": "datetime",
            "sort": "desc",
        }
        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=60.0)
            try:
                response = await client.get(
                    f"{OPENAQ_BASE}/sensors/{sensor_id}/measurements",
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
            finally:
                if self._owns_client:
                    await client.aclose()

        if not isinstance(payload, dict):
            return None
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return None
        first = results[0]
        if not isinstance(first, dict):
            return None
        value = first.get("value")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

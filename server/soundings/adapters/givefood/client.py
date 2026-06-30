"""Async HTTP client for the Give Food food-bank dump.

One endpoint: the daily JSON dump of all UK food-bank locations. Each row is
trimmed to the fields Soundings uses. Identifies itself via a User-Agent per
Give Food's terms.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

DUMP_URL = "https://www.givefood.org.uk/dumps/foodbanks/json/latest/"
GIVEFOOD_HEADERS = {
    "User-Agent": "Soundings/1.0 (open insight commons; +https://github.com/dataforaction/soundings)",
    "Accept": "application/json",
}


class GiveFoodUnavailableError(RuntimeError):
    """Raised when the Give Food dump cannot be fetched or parsed.

    Distinguishes a transport/parse failure (which must surface as a caveat)
    from a genuine empty result, so the adapter never caches a fabricated 0.
    """


def _trim(row: dict[str, Any]) -> dict[str, Any]:
    """Reduce a dump row to the fields Soundings uses; parse `lat_lng`."""
    lat: float | None = None
    lng: float | None = None
    lat_lng = row.get("lat_lng") or ""
    if isinstance(lat_lng, str) and "," in lat_lng:
        a, _, b = lat_lng.partition(",")
        try:
            lat, lng = float(a), float(b)
        except ValueError:
            lat, lng = None, None
    name = (row.get("location_name") or row.get("organisation_name") or "").strip() or "Food bank"
    lsoa = row.get("lsoa")
    return {
        "lat": lat,
        "lng": lng,
        "postcode": row.get("postcode"),
        "lsoa": lsoa if isinstance(lsoa, str) and lsoa else None,
        "name": name,
        "org": row.get("organisation_name"),
    }


class GiveFoodClient:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client
        self._owns_client = http_client is None

    async def fetch_foodbanks(self) -> list[dict[str, Any]]:
        """Fetch + trim the full food-bank dump. Raises on failure."""
        client = self._client or httpx.AsyncClient(timeout=60.0)
        try:
            response = await client.get(DUMP_URL, headers=GIVEFOOD_HEADERS, follow_redirects=True)
            response.raise_for_status()
            data: Any = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise GiveFoodUnavailableError(f"Give Food dump fetch failed: {exc!r}") from exc
        finally:
            if self._owns_client:
                await client.aclose()

        if not isinstance(data, list):
            raise GiveFoodUnavailableError("Give Food dump was not a JSON list")
        return [_trim(row) for row in data if isinstance(row, dict)]

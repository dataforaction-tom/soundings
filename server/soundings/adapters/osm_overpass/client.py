"""Async HTTP wrapper for the OpenStreetMap Overpass API.

Primary endpoint: Britain & Ireland instance.
Fallback: main Overpass instance.

Overpass queries are POST requests with body `data=<Overpass QL query>`.
The client only issues count queries — `out count;` — returning the total
number of matching elements (nodes + ways + relations) within a bounding box.
"""

from __future__ import annotations

from typing import Any

import httpx
from aiolimiter import AsyncLimiter

OVERPASS_PRIMARY = "https://overpass.atownsend.org.uk/api/interpreter"
OVERPASS_FALLBACK = "https://overpass-api.de/api/interpreter"


class OsmOverpassClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        rate_per_second: float = 2.0,
    ) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._limiter = AsyncLimiter(max_rate=rate_per_second, time_period=1)

    async def count_by_tag(
        self,
        tag_key: str,
        tag_value: str,
        bbox: tuple[float, float, float, float],
    ) -> int:
        """POST a count query for the given tag within the bounding box.

        Returns total count (nodes + ways + relations). Falls back to the
        main instance if the primary fails. Returns 0 if the response shape
        is unexpected or the count element is missing.
        """
        south, west, north, east = bbox
        bbox_str = f"{south},{west},{north},{east}"
        query = (
            f"[out:json][timeout:25];\n"
            f"(\n"
            f'  node["{tag_key}"="{tag_value}"]({bbox_str});\n'
            f'  way["{tag_key}"="{tag_value}"]({bbox_str});\n'
            f'  relation["{tag_key}"="{tag_value}"]({bbox_str});\n'
            f");\n"
            f"out count;\n"
        )
        return await self._post_count(query)

    async def _post_count(self, query: str) -> int:
        """Send the count query, trying primary then fallback endpoint."""
        for endpoint in (OVERPASS_PRIMARY, OVERPASS_FALLBACK):
            try:
                count = await self._post(endpoint, query)
            except (httpx.HTTPError, httpx.HTTPStatusError):
                continue
            if count is not None:
                return count
        return 0

    async def _post(self, endpoint: str, query: str) -> int | None:
        """POST to a single endpoint. Returns the count or None on failure."""
        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=60.0)
            try:
                response = await client.post(
                    endpoint,
                    data={"data": query},
                )
                response.raise_for_status()
                payload: Any = response.json()
            finally:
                if self._owns_client:
                    await client.aclose()

        return _extract_total(payload)


def _extract_total(payload: Any) -> int | None:
    """Extract the total count from an Overpass count response."""
    if not isinstance(payload, dict):
        return None
    elements = payload.get("elements")
    if not isinstance(elements, list):
        return None
    for el in elements:
        if not isinstance(el, dict):
            continue
        if el.get("type") != "count":
            continue
        tags = el.get("tags")
        if not isinstance(tags, dict):
            continue
        total = tags.get("total")
        if total is None:
            continue
        try:
            return int(total)
        except (TypeError, ValueError):
            return None
    return None

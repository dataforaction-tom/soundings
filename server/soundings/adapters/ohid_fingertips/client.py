"""Async HTTP wrapper for the OHID Fingertips API.

Base: https://fingertips.phe.org.uk/api/

The public API is unauthenticated. We hit
`/latest_data/all_indicators_in_profile_group_for_child_areas` which
returns every indicator × sex × age × area for a given
(profile_id, group_id, area_type_id) page. This is the one data
endpoint that reliably returns JSON; the `/all_data/json/by_indicator_id`
endpoint older docs mention currently 500s.

Multiple soundings indicator keys can share a single response page,
so the adapter caches the response by (profile_id, group_id,
area_type_id) and filters client-side.
"""

from typing import Any

import httpx
from aiolimiter import AsyncLimiter

FINGERTIPS_BASE = "https://fingertips.phe.org.uk/api"


class FingertipsClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        rate_per_second: float = 4.0,
    ) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._limiter = AsyncLimiter(max_rate=rate_per_second, time_period=1)

    async def get_group_data(
        self,
        *,
        profile_id: int,
        group_id: int,
        area_type_id: int,
        parent_area_code: str = "E92000001",
    ) -> list[dict[str, Any]]:
        """Returns the full (indicator × sex × age × area) page.

        Each top-level record has:
          - Grouping: list of metadata entries with IndicatorId, GroupingId
          - Sex: {Id, Name}
          - Age: {Id, Name}
          - Data: list of {AreaCode, Val, Year, ...} per area
        """
        params: dict[str, str | int] = {
            "profile_id": profile_id,
            "group_id": group_id,
            "area_type_id": area_type_id,
            "parent_area_code": parent_area_code,
        }
        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            try:
                response = await client.get(
                    f"{FINGERTIPS_BASE}/latest_data/all_indicators_in_profile_group_for_child_areas",
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
            finally:
                if self._owns_client:
                    await client.aclose()

        if not isinstance(payload, list):
            return []
        return payload

"""Async HTTP wrapper for the OHID Fingertips API.

Base: https://fingertips.phe.org.uk/api/

The public API is unauthenticated. We use the `/all_data/json/by_indicator_id`
endpoint which returns every area of a given `child_area_type_id` for a
single indicator id; we filter client-side to the requested place_ids.
A single call returns ~320 LAs × ~10 years for a typical indicator —
cheap enough that we don't try to query by specific area code.

Documentation moves around; if `/all_data/json/by_indicator_id` returns
4xx the live test (Task 11) is the canary.
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

    async def get_indicator_data(
        self,
        *,
        indicator_id: int,
        child_area_type_id: int,
        parent_area_type_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Returns the full series for every child-area of the supplied type.

        Each record looks like:
            {"AreaCode": "E06000004", "AreaName": "Stockton-on-Tees",
             "Sex": "Female", "Age": "All ages", "Value": 81.2,
             "TimePeriod": "2020 - 22", "Year": 2022, ...}
        """
        params: dict[str, str | int] = {
            "indicator_id": indicator_id,
            "child_area_type_id": child_area_type_id,
        }
        if parent_area_type_id is not None:
            params["parent_area_type_id"] = parent_area_type_id

        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            try:
                response = await client.get(
                    f"{FINGERTIPS_BASE}/all_data/json/by_indicator_id",
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

"""Async HTTP wrapper for the Nomis Open Data API.

https://www.nomisweb.co.uk/api/ — public, no auth required for indicator
data we use (Census 2021, Mid-Year Estimates). An optional `NOMIS_API_KEY`
in the environment unlocks higher rate limits and is forwarded as the
`uid` query parameter.
"""

import os
from typing import Any

import httpx
from aiolimiter import AsyncLimiter

NOMIS_HOST = "https://www.nomisweb.co.uk/api/v01"


class NomisClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        rate_per_second: float = 2.0,
    ) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._limiter = AsyncLimiter(max_rate=rate_per_second, time_period=1)

    async def get_observations(
        self,
        *,
        dataset_id: str,
        geography: str,
        measures: str | None = None,
        time: str | None = None,
        **extra: str,
    ) -> dict[str, Any]:
        params: dict[str, str] = {"geography": geography}
        if measures:
            params["measures"] = measures
        if time:
            params["time"] = time
        for k, v in extra.items():
            params[k] = v
        api_key = os.environ.get("NOMIS_API_KEY")
        if api_key:
            params["uid"] = api_key

        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            try:
                response = await client.get(
                    f"{NOMIS_HOST}/dataset/{dataset_id}.data.json", params=params
                )
                response.raise_for_status()
                payload: dict[str, Any] = response.json()
            finally:
                if self._owns_client:
                    await client.aclose()
        return payload

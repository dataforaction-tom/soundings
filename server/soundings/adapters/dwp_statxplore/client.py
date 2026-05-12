"""Async HTTP wrapper for the DWP Stat-Xplore API.

Base: https://stat-xplore.dwp.gov.uk/webapi/rest/v1/

Requires `STATXPLORE_API_KEY` in the `APIKey` header. Free signup at
<https://stat-xplore.dwp.gov.uk/>.

Stat-Xplore organises data as "cubes" (also called "datasets"). To
query a cube, POST a JSON body specifying database, measures,
dimensions, and recodes. The response is a hypercube of values.

Cube field/value identifiers are long strings like
`str:field:UC_Households:V_F_UC_HOUSEHOLDS:GEOGRAPHY`. They're
documented at the Stat-Xplore web UI but require the API key to
discover programmatically via `/schema`.
"""

import os
from typing import Any

import httpx
from aiolimiter import AsyncLimiter

STATXPLORE_BASE = "https://stat-xplore.dwp.gov.uk/webapi/rest/v1"


class StatXploreClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        rate_per_second: float = 2.0,
        api_key: str | None = None,
    ) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._limiter = AsyncLimiter(max_rate=rate_per_second, time_period=1)
        # Allow explicit override; otherwise read from env at construction.
        # Note: env is read lazily on each call so secret rotation doesn't
        # require app restart.
        self._explicit_api_key = api_key

    def _api_key(self) -> str | None:
        return self._explicit_api_key or os.environ.get("STATXPLORE_API_KEY")

    async def get_table(
        self,
        *,
        database: str,
        measures: list[str],
        dimensions: list[list[str]],
        recodes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST a cube query and return the parsed JSON response.

        `database`, `measures`, and `dimension` entries are Stat-Xplore's
        long-form identifier strings. `recodes` is optional — used to
        select specific geography codes or aggregate dimensions.
        """
        api_key = self._api_key()
        if not api_key:
            raise RuntimeError("STATXPLORE_API_KEY is not set — cannot query Stat-Xplore")

        body: dict[str, Any] = {
            "database": database,
            "measures": measures,
            "dimensions": dimensions,
        }
        if recodes:
            body["recodes"] = recodes

        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=60.0)
            try:
                response = await client.post(
                    f"{STATXPLORE_BASE}/table",
                    json=body,
                    headers={
                        "APIKey": api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                response.raise_for_status()
                payload = response.json()
            finally:
                if self._owns_client:
                    await client.aclose()

        if not isinstance(payload, dict):
            return {}
        return payload

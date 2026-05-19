"""Async HTTP client for the Find That Charity API.

Base: https://findthatcharity.uk/api/

Public, no auth required. Two endpoints:

- `GET /charity/{id}` — single-charity detail lookup by registered ID
  (cross-regulator: GB-CHC-NNNNNN for England/Wales, SC-NNNNNN for Scotland,
  NI-NNNNNN for Northern Ireland).
- `GET /charity/search` — cross-jurisdiction search with filters:
  `name`, `postcode`, `country`.

Used by the FindThatCharityAdapter to provide organisation lookup for
Scotland and Northern Ireland (E&W uses the Charity Commission loader).
"""

from dataclasses import dataclass
from typing import Any

import httpx
from aiolimiter import AsyncLimiter

FIND_THAT_CHARITY_BASE = "https://findthatcharity.uk/api"


@dataclass
class CharityDetail:
    """Full charity detail from FTC."""

    id: str  # e.g., "GB-CHC-123456" or "SC012345"
    name: str
    registered_date: str | None
    postcode: str | None
    country: str  # "England", "Wales", "Scotland", "Northern Ireland"
    status: str  # "Registered", "Removed", etc.
    activities: str | None
    charitable_objects: str | None
    source_url: str


@dataclass
class CharitySearchResult:
    """Single result from the FTC search endpoint."""

    id: str
    name: str
    postcode: str | None
    country: str


class FindThatCharityClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        rate_per_second: float = 4.0,
    ) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._limiter = AsyncLimiter(max_rate=rate_per_second, time_period=1)

    async def get_charity(self, charity_id: str) -> CharityDetail | None:
        """Fetch detail for a single charity by its registered ID.

        Args:
            charity_id: The cross-regulator ID (e.g., "GB-CHC-123456",
                "SC012345", "NI123456").

        Returns:
            CharityDetail if found, None if 404.
        """
        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            try:
                response = await client.get(f"{FIND_THAT_CHARITY_BASE}/charity/{charity_id}")
            finally:
                if self._owns_client:
                    await client.aclose()

        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        return self._parse_charity_detail(payload)

    async def search(
        self,
        name: str | None = None,
        postcode: str | None = None,
        country: str | None = None,
        limit: int = 50,
    ) -> list[CharitySearchResult]:
        """Search for charities across jurisdictions.

        Args:
            name: Name search term (partial match).
            postcode: Postcode to search within.
            country: Filter by country ("England", "Wales", "Scotland",
                "Northern Ireland").
            limit: Maximum results to return.

        Returns:
            List of CharitySearchResult objects.
        """
        params: dict[str, Any] = {"limit": limit}
        if name:
            params["name"] = name
        if postcode:
            params["postcode"] = postcode
        if country:
            params["country"] = country

        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            try:
                response = await client.get(
                    f"{FIND_THAT_CHARITY_BASE}/charity/search",
                    params=params,
                )
            finally:
                if self._owns_client:
                    await client.aclose()

        response.raise_for_status()
        payload = response.json()

        results: list[CharitySearchResult] = []
        for item in payload.get("results", []):
            results.append(
                CharitySearchResult(
                    id=item.get("id", ""),
                    name=item.get("name", ""),
                    postcode=item.get("postcode"),
                    country=item.get("country", ""),
                )
            )
        return results

    def _parse_charity_detail(self, payload: dict[str, Any]) -> CharityDetail:
        """Parse the FTC charity detail response into a typed dataclass."""
        return CharityDetail(
            id=payload.get("id", ""),
            name=payload.get("name", ""),
            registered_date=payload.get("registered_date"),
            postcode=payload.get("postcode"),
            country=payload.get("country", ""),
            status=payload.get("status", ""),
            activities=payload.get("activities"),
            charitable_objects=payload.get("charitable_objects"),
            source_url=payload.get("url", ""),
        )

"""Find That Charity adapter — passthrough mode for cross-jurisdiction lookup.

This adapter provides organisation lookup for Scotland and Northern Ireland.
England/Wales uses the Charity Commission loader (data.organisation table).

Per Phase 4 Block C:
- source_id: "find_that_charity"
- mode: "passthrough"
- ttl: 168 hours (weekly)

Does NOT publish indicators (FTC count is unreliable — it aggregates
multiple regulators). Only implements `fetch_organisations`:
- Scotland → search with country=Scotland
- Northern Ireland → country=Northern Ireland
- England/Wales → returns [] (E&W goes via CC loader)
"""

from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.find_that_charity.client import FindThatCharityClient
from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.contracts.organisation import OrganisationRef

SOURCE_ID = "find_that_charity"
DEFAULT_TTL = timedelta(hours=168)


class FindThatCharityAdapter(PassthroughAdapter):
    source_id = SOURCE_ID

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        ttl: timedelta = DEFAULT_TTL,
        ftc_client: FindThatCharityClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(engine, ttl=ttl, http_client=http_client)
        self._ftc = ftc_client or FindThatCharityClient(http_client=http_client)

    async def fetch_organisations(
        self,
        place_id: str,
        filters: list[str] | None = None,
        limit: int = 50,
    ) -> list[OrganisationRef]:
        """Return organisations for a place via FTC.

        Routes based on place country (derived from place_id prefix):
        - Scotland -> country=Scotland
        - NI -> country=Northern Ireland
        - England/Wales -> returns [] (E&W goes via CC loader)
        """
        # Resolve place country from place_id prefix (no DB round-trip needed)
        country = self._country_from_place_id(place_id)

        if country == "Scotland":
            ftc_country = "Scotland"
        elif country == "Northern Ireland":
            ftc_country = "Northern Ireland"
        else:
            # England/Wales -> E&W goes via CC loader, not FTC
            return []

        try:
            results = await self._ftc.search(
                country=ftc_country,
                limit=limit,
            )
        except Exception:
            # FTC lookup failed — return empty with caveat in orchestrator
            return []

        source_ref = await self._build_source_ref(
            retrieved_at=self._now(),
            cache_status="live",
        )

        return [
            OrganisationRef(
                id=r.id,
                name=r.name,
                classification=[],
                registered_address_place_id=None,  # FTC doesn't give us this
                operates_in_place_ids=[],
                recent_grants=[],
                source=source_ref,
            )
            for r in results
        ]

    def _country_from_place_id(self, place_id: str) -> str | None:
        """Derive country from place_id prefix — no DB query needed."""
        if place_id.startswith("country:S"):
            return "Scotland"
        if place_id.startswith("country:NI"):
            return "Northern Ireland"
        if place_id.startswith(("ltla24:S", "utla24:S")):
            return "Scotland"
        if place_id.startswith(("ltla24:N", "utla24:N")):
            return "Northern Ireland"

        # Default to England for English LTLAs/UTLAs/regions
        # We can't always know if it's Wales, but FTC handles both
        return "England"

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str):
        """Not used — indicators are not published by this adapter."""
        raise NotImplementedError("FindThatCharityAdapter does not publish indicators")

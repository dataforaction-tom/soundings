"""Async HTTP wrapper for the 360Giving Datastore API.

Base: https://api.threesixtygiving.org/api/v1

Public, no auth required. Two endpoints we use:

- `GET /org/{org_id}/` — single-org lifetime aggregate (used as a
  cheap "any grants in window?" filter before paginating the full
  list).
- `GET /org/{org_id}/grants_received/?limit=N&offset=M` — paginated
  grants where this org was the recipient.

The API is org-centric — no place-based search. Block B composes
place-based aggregates by fanning out across the charities in
`data.organisation` (CC-loaded), aggregated by
`registered_address_place_id`.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from aiolimiter import AsyncLimiter

THREESIXTYGIVING_BASE = "https://api.threesixtygiving.org/api/v1"


@dataclass
class OrgAggregate:
    org_id: str
    grants: int
    total_gbp: float
    earliest_grant_date: str | None
    latest_grant_date: str | None


class ThreeSixtyGivingClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        rate_per_second: float = 4.0,
    ) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._limiter = AsyncLimiter(max_rate=rate_per_second, time_period=1)

    async def get_org_aggregate(self, org_id: str) -> OrgAggregate | None:
        """Returns lifetime recipient stats for an org, or None if the
        org isn't in 360G's universe / has no recipient grants."""
        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=30.0)
            try:
                response = await client.get(f"{THREESIXTYGIVING_BASE}/org/{org_id}/")
            finally:
                if self._owns_client:
                    await client.aclose()
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        recipient = payload.get("recipient") if isinstance(payload, dict) else None
        if not recipient:
            return None
        aggregate = recipient.get("aggregate") or {}
        currencies = aggregate.get("currencies") or {}
        gbp = currencies.get("GBP") or {}
        return OrgAggregate(
            org_id=str(payload.get("org_id", org_id)),
            grants=int(aggregate.get("grants") or 0),
            total_gbp=float(gbp.get("total") or 0.0),
            earliest_grant_date=aggregate.get("earliest_grant_date"),
            latest_grant_date=aggregate.get("latest_grant_date"),
        )

    async def iter_grants_received(
        self,
        org_id: str,
        *,
        page_size: int = 50,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield every grant where this org is the recipient.

        Follows the `next` pagination URL until exhausted. Each yielded
        dict is the raw grant payload (with `grant_id` + a `data`
        sub-object carrying the 360G fields: awardDate, amountAwarded,
        fundingOrganization, recipientOrganization, beneficiaryLocation
        etc.). Caller filters by date / sums by currency.
        """
        url: str | None = f"{THREESIXTYGIVING_BASE}/org/{org_id}/grants_received/?limit={page_size}"
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            while url is not None:
                async with self._limiter:
                    response = await client.get(url)
                if response.status_code == 404:
                    return
                response.raise_for_status()
                payload = response.json()
                for grant in payload.get("results") or []:
                    yield grant
                next_url = payload.get("next")
                url = str(next_url) if next_url else None
        finally:
            if self._owns_client:
                await client.aclose()

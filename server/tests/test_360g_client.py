"""Unit tests for ThreeSixtyGivingClient (mock transport).

The real API is org-centric — no place-based search. Our client wraps:

- `GET /api/v1/org/{org_id}/` → lifetime aggregate stats per org.
- `GET /api/v1/org/{org_id}/grants_received/?limit=N&offset=M` →
  paginated grants where the org is the recipient.

Block B fans these out across the charities in `data.organisation`
to compose place-based aggregates. No auth required.
"""

import httpx
import pytest

from soundings.adapters.threesixtygiving.client import (
    THREESIXTYGIVING_BASE,
    ThreeSixtyGivingClient,
)


async def test_get_org_aggregate_returns_lifetime_recipient_stats() -> None:
    """`/api/v1/org/{org_id}/` returns recipient.aggregate.{grants,
    currencies.GBP.total, latest_grant_date} — we use latest_grant_date
    as the cheap filter to skip orgs with no recent grants."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "org_id": "GB-CHC-202918",
                "name": "Oxfam",
                "recipient": {
                    "aggregate": {
                        "grants": 45,
                        "earliest_grant_date": "2002-12-18",
                        "latest_grant_date": "2026-03-13",
                        "currencies": {
                            "GBP": {
                                "total": 18268841.47,
                                "grants": 45,
                                "avg": 405974.25,
                                "min": 250.0,
                                "max": 3000000.0,
                            }
                        },
                    }
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = ThreeSixtyGivingClient(http_client=http)
        aggregate = await client.get_org_aggregate("GB-CHC-202918")

    assert captured["url"] == f"{THREESIXTYGIVING_BASE}/org/GB-CHC-202918/"
    assert aggregate is not None
    assert aggregate.grants == 45
    assert aggregate.total_gbp == pytest.approx(18268841.47)
    assert aggregate.latest_grant_date == "2026-03-13"


async def test_get_org_aggregate_returns_none_for_org_with_no_grants() -> None:
    """An org with no recipient grants returns recipient: null."""
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json={
                "org_id": "GB-CHC-999",
                "name": "Empty",
                "recipient": None,
            },
        )
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = ThreeSixtyGivingClient(http_client=http)
        aggregate = await client.get_org_aggregate("GB-CHC-999")
    assert aggregate is None


async def test_get_org_aggregate_handles_404() -> None:
    """Unknown org → None, not an exception. CC orgs we know about
    might not all be in 360G's universe."""
    transport = httpx.MockTransport(lambda req: httpx.Response(404))
    async with httpx.AsyncClient(transport=transport) as http:
        client = ThreeSixtyGivingClient(http_client=http)
        aggregate = await client.get_org_aggregate("GB-CHC-MISSING")
    assert aggregate is None


async def test_iter_grants_received_paginates() -> None:
    """The client follows `next` until exhausted, yielding flattened
    grant dicts. Real responses are paginated 50/page by default."""
    pages = [
        {
            "count": 3,
            "next": f"{THREESIXTYGIVING_BASE}/org/GB-CHC-X/grants_received/?offset=2",
            "previous": None,
            "results": [
                {"grant_id": "g1", "data": {"awardDate": "2024-08-01", "amountAwarded": 1000.0}},
                {"grant_id": "g2", "data": {"awardDate": "2025-01-15", "amountAwarded": 5000.0}},
            ],
        },
        {
            "count": 3,
            "next": None,
            "previous": None,
            "results": [
                {"grant_id": "g3", "data": {"awardDate": "2025-08-20", "amountAwarded": 2500.0}},
            ],
        },
    ]
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        page = pages[call_count]
        call_count += 1
        return httpx.Response(200, json=page)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = ThreeSixtyGivingClient(http_client=http)
        grants = [g async for g in client.iter_grants_received("GB-CHC-X")]

    assert call_count == 2
    assert len(grants) == 3
    assert [g["grant_id"] for g in grants] == ["g1", "g2", "g3"]


async def test_iter_grants_received_returns_empty_on_404() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(404))
    async with httpx.AsyncClient(transport=transport) as http:
        client = ThreeSixtyGivingClient(http_client=http)
        grants = [g async for g in client.iter_grants_received("GB-CHC-MISSING")]
    assert grants == []


async def test_iter_grants_received_passes_limit_param() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"count": 0, "next": None, "results": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = ThreeSixtyGivingClient(http_client=http)
        grants = [g async for g in client.iter_grants_received("GB-CHC-X", page_size=200)]
    assert grants == []
    assert "limit=200" in captured["url"]


async def test_client_rate_limited_to_polite_rps() -> None:
    """Sanity: aiolimiter is in the call path (we don't hammer the
    upstream when fanning out across hundreds of charities)."""
    # Effectively a smoke for the limiter being instantiated; we just
    # confirm three sequential calls all return cleanly.
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"org_id": "x", "name": "x", "recipient": None})
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = ThreeSixtyGivingClient(http_client=http)
        for _ in range(3):
            await client.get_org_aggregate("GB-CHC-X")

"""Tests for ThreeSixtyGivingAdapter.

The adapter is passthrough but composes place-level aggregates by
fanning out across the charities in `data.organisation` (CC-loaded).
Each charity's grants list is cached per-org; the per-place aggregate
is also cached.

Tests seed a small `data.organisation` set, mock the 360G HTTP API
via `httpx.MockTransport`, and assert the place-level aggregation +
caching behaviour.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from soundings.adapters.threesixtygiving.adapter import ThreeSixtyGivingAdapter
from soundings.adapters.threesixtygiving.client import ThreeSixtyGivingClient
from soundings.catalogue.loader import load_catalogue_into_db
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _cleanup() -> AsyncIterator[None]:
    yield
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.organisation_operates_in"))
        await conn.execute(text("DELETE FROM data.organisation"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))


async def _seed_three_charities_for_stockton() -> None:
    """Three charities registered in Stockton, with `id` matching the
    CC namespace convention so the adapter can convert them to 360G
    `GB-CHC-{n}` org_ids."""
    engine = get_engine()
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    await load_catalogue_into_db(
        engine,
        sources_path=repo_root / "catalogue" / "sources.yaml",
        indicators_path=repo_root / "catalogue" / "indicators.yaml",
    )
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.organisation_operates_in"))
        await conn.execute(text("DELETE FROM data.organisation"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:E06000004', 'ltla24', 'E06000004', 'Stockton-on-Tees')"
            )
        )
        for reg in ["1001", "1002", "1003"]:
            await conn.execute(
                text(
                    "INSERT INTO data.organisation "
                    "(id, name, classification, registered_address_place_id, "
                    "source_id, retrieved_at, raw) VALUES "
                    "(:id, :name, ARRAY[]::varchar[], 'ltla24:E06000004', "
                    "'charity_commission', NOW(), '{}'::jsonb)"
                ),
                {"id": f"charity_commission:{reg}", "name": f"Charity {reg}"},
            )


def _aggregate_payload(grants: int, total_gbp: float, latest: str) -> dict[str, Any]:
    return {
        "org_id": "GB-CHC-1001",
        "name": "test",
        "recipient": {
            "aggregate": {
                "grants": grants,
                "earliest_grant_date": "2020-01-01",
                "latest_grant_date": latest,
                "currencies": {"GBP": {"total": total_gbp, "grants": grants}},
            }
        },
    }


def _grants_received_payload(grants: list[tuple[str, float]]) -> dict[str, Any]:
    return {
        "count": len(grants),
        "next": None,
        "previous": None,
        "results": [
            {
                "grant_id": f"g-{i}",
                "data": {
                    "id": f"g-{i}",
                    "title": f"Grant {i}",
                    "awardDate": date,
                    "amountAwarded": amount,
                    "currency": "GBP",
                    "fundingOrganization": [{"name": f"Funder {i}"}],
                    "recipientOrganization": [{"id": "GB-CHC-1001"}],
                },
            }
            for i, (date, amount) in enumerate(grants)
        ],
    }


async def _adapter(http: httpx.AsyncClient) -> ThreeSixtyGivingAdapter:
    client = ThreeSixtyGivingClient(http_client=http)
    return ThreeSixtyGivingAdapter(
        get_engine(),
        threesixtygiving_client=client,
        now=lambda: datetime(2026, 5, 12, tzinfo=UTC),
    )


async def test_grants_in_last_12m_total_sums_recent_grants_across_charities() -> None:
    """Three charities; each has aggregate.latest_grant_date within 12mo
    AND a couple of recent grants. The adapter sums them."""
    await _seed_three_charities_for_stockton()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/grants_received/" in url:
            # Each charity returns 2 recent grants, total £15k each.
            return httpx.Response(
                200,
                json=_grants_received_payload([("2025-08-01", 10_000.0), ("2026-02-15", 5_000.0)]),
            )
        return httpx.Response(
            200,
            json=_aggregate_payload(grants=2, total_gbp=15_000.0, latest="2026-02-15"),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = await _adapter(http)
        iv = await adapter.fetch_indicator(
            "civil_society.grants_in_last_12m_total",
            "ltla24:E06000004",
            period=None,
        )

    assert iv is not None
    assert iv.value == pytest.approx(45_000.0)  # 3 charities × £15k each
    assert iv.unit == "GBP"
    assert iv.source.source_id == "threesixtygiving"


async def test_grants_in_last_12m_count_counts_recent_grants() -> None:
    await _seed_three_charities_for_stockton()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/grants_received/" in url:
            return httpx.Response(
                200,
                json=_grants_received_payload([("2025-08-01", 10_000.0), ("2026-02-15", 5_000.0)]),
            )
        return httpx.Response(
            200,
            json=_aggregate_payload(grants=2, total_gbp=15_000.0, latest="2026-02-15"),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = await _adapter(http)
        iv = await adapter.fetch_indicator(
            "civil_society.grants_in_last_12m_count",
            "ltla24:E06000004",
            period=None,
        )

    assert iv is not None
    assert iv.value == 6.0  # 3 charities × 2 grants each


async def test_latest_grant_date_optimisation_skips_stale_orgs() -> None:
    """Orgs whose latest grant predates the 12m window contribute 0 to
    the aggregate AND don't trigger a paginated grants_received call —
    the latest_grant_date in the aggregate is enough to short-circuit."""
    await _seed_three_charities_for_stockton()
    grants_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal grants_calls
        url = str(request.url)
        if "/grants_received/" in url:
            grants_calls += 1
            return httpx.Response(
                200,
                json=_grants_received_payload([("2026-01-01", 10_000.0)]),
            )
        # Aggregate says: latest grant was in 2022 → outside the 12m window
        # ending May 2026.
        return httpx.Response(
            200,
            json=_aggregate_payload(grants=5, total_gbp=100_000.0, latest="2022-06-01"),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = await _adapter(http)
        iv = await adapter.fetch_indicator(
            "civil_society.grants_in_last_12m_total",
            "ltla24:E06000004",
            period=None,
        )

    assert iv is not None
    assert iv.value == 0.0
    # Zero paginated grants_received fetches because every org's
    # latest_grant_date is older than the window.
    assert grants_calls == 0


async def test_grants_aggregate_is_cached_per_place() -> None:
    """Two fetch_indicator calls for the same place → only one fan-out."""
    await _seed_three_charities_for_stockton()
    aggregate_calls = 0
    grants_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal aggregate_calls, grants_calls
        url = str(request.url)
        if "/grants_received/" in url:
            grants_calls += 1
            return httpx.Response(
                200,
                json=_grants_received_payload([("2026-01-01", 1_000.0)]),
            )
        aggregate_calls += 1
        return httpx.Response(
            200,
            json=_aggregate_payload(grants=1, total_gbp=1_000.0, latest="2026-01-01"),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = await _adapter(http)
        await adapter.fetch_indicator(
            "civil_society.grants_in_last_12m_total",
            "ltla24:E06000004",
            period=None,
        )
        first_aggregate = aggregate_calls
        first_grants = grants_calls
        await adapter.fetch_indicator(
            "civil_society.grants_in_last_12m_total",
            "ltla24:E06000004",
            period=None,
        )
    # Second call entirely cached at the per-place level.
    assert first_aggregate == 3  # 3 charities
    assert first_grants == 3
    assert aggregate_calls == first_aggregate
    assert grants_calls == first_grants


async def test_unknown_indicator_returns_none() -> None:
    await _seed_three_charities_for_stockton()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = await _adapter(http)
        iv = await adapter.fetch_indicator(
            "civil_society.not_an_indicator", "ltla24:E06000004", period=None
        )
    assert iv is None


async def test_place_with_no_charities_returns_zero() -> None:
    """An LTLA with no CC charities registered there → 0 total, 0 count.
    Caveat surfaces the cause."""
    # Seed an LTLA but no charities for it.
    engine = get_engine()
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    await load_catalogue_into_db(
        engine,
        sources_path=repo_root / "catalogue" / "sources.yaml",
        indicators_path=repo_root / "catalogue" / "indicators.yaml",
    )
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.organisation_operates_in"))
        await conn.execute(text("DELETE FROM data.organisation"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:E99999999', 'ltla24', 'E99999999', 'No Charities')"
            )
        )

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = await _adapter(http)
        iv = await adapter.fetch_indicator(
            "civil_society.grants_in_last_12m_total",
            "ltla24:E99999999",
            period=None,
        )
    assert iv is not None
    assert iv.value == 0.0
    assert any("no charities" in c.lower() for c in iv.caveats)


async def test_recent_grants_returns_top_n_sorted_by_date() -> None:
    """Block D's find_organisations_in_place uses this to enrich
    OrganisationRef.recent_grants. Most recent first; capped at limit."""
    await _seed_three_charities_for_stockton()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/grants_received/" in url:
            return httpx.Response(
                200,
                json=_grants_received_payload(
                    [
                        ("2024-01-01", 100.0),
                        ("2025-08-01", 200.0),
                        ("2026-02-15", 300.0),
                    ]
                ),
            )
        return httpx.Response(
            200,
            json=_aggregate_payload(grants=3, total_gbp=600.0, latest="2026-02-15"),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = await _adapter(http)
        grants = await adapter.recent_grants("ltla24:E06000004", limit=5)

    # 3 charities × 3 grants = 9, top 5 by date:
    assert len(grants) == 5
    # Most recent first.
    dates = [g.date for g in grants]
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == "2026-02-15"

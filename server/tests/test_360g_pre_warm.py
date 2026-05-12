"""Tests for ThreeSixtyGivingAdapter.pre_warm_for_places.

The pre_warmer daemon (Block 0) calls this on a weekly cron, passing
the full LTLA universe. We assert two behaviours:

1. After pre_warm, a subsequent fetch_indicator hits the cache without
   any upstream calls.
2. A misbehaving org (HTTP 5xx) for one LTLA doesn't poison the
   pre-warm pass for other LTLAs.
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


async def _seed_two_ltlas_with_charities() -> None:
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
        for code, name in [
            ("E06000004", "Stockton"),
            ("E06000001", "Hartlepool"),
        ]:
            await conn.execute(
                text(
                    "INSERT INTO geography.place (id, type, code, name) "
                    "VALUES (:id, 'ltla24', :code, :name)"
                ),
                {"id": f"ltla24:{code}", "code": code, "name": name},
            )
        # 1 charity per LTLA — enough to exercise the fan-out.
        for reg, code in [("1001", "E06000004"), ("2002", "E06000001")]:
            await conn.execute(
                text(
                    "INSERT INTO data.organisation "
                    "(id, name, classification, registered_address_place_id, "
                    "source_id, retrieved_at, raw) VALUES "
                    "(:id, :name, ARRAY[]::varchar[], :pid, 'charity_commission', "
                    "NOW(), '{}'::jsonb)"
                ),
                {
                    "id": f"charity_commission:{reg}",
                    "name": f"Charity {reg}",
                    "pid": f"ltla24:{code}",
                },
            )


def _aggregate_payload(latest: str = "2026-02-15") -> dict[str, Any]:
    return {
        "org_id": "GB-CHC-1001",
        "name": "test",
        "recipient": {
            "aggregate": {
                "grants": 1,
                "earliest_grant_date": "2025-08-01",
                "latest_grant_date": latest,
                "currencies": {"GBP": {"total": 1000.0, "grants": 1}},
            }
        },
    }


def _grants_payload() -> dict[str, Any]:
    return {
        "count": 1,
        "next": None,
        "results": [
            {
                "grant_id": "g1",
                "data": {
                    "id": "g1",
                    "currency": "GBP",
                    "awardDate": "2026-02-15",
                    "amountAwarded": 1000.0,
                    "fundingOrganization": [{"name": "Test Funder"}],
                    "title": "Test grant",
                },
            }
        ],
    }


async def test_pre_warm_populates_cache_so_subsequent_fetch_is_zero_upstream() -> None:
    await _seed_two_ltlas_with_charities()

    api_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        api_calls += 1
        url = str(request.url)
        if "/grants_received/" in url:
            return httpx.Response(200, json=_grants_payload())
        return httpx.Response(200, json=_aggregate_payload())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = ThreeSixtyGivingAdapter(
            get_engine(),
            threesixtygiving_client=ThreeSixtyGivingClient(http_client=http),
            now=lambda: datetime(2026, 5, 12, tzinfo=UTC),
        )
        # Pre-warm both LTLAs.
        await adapter.pre_warm_for_places(["ltla24:E06000004", "ltla24:E06000001"])
        pre_warm_calls = api_calls

        # User-facing fetch — should be all cache.
        iv = await adapter.fetch_indicator(
            "civil_society.grants_in_last_12m_total",
            "ltla24:E06000004",
            period=None,
        )
    assert iv is not None
    assert iv.value == pytest.approx(1000.0)
    # Zero additional API calls after pre-warm.
    assert api_calls == pre_warm_calls


async def test_pre_warm_swallows_failures_per_place() -> None:
    """One LTLA's API fan-out blowing up shouldn't stop the daemon
    from processing the next LTLA. We exercise via a handler that
    raises for one specific org, succeeds for the other."""
    await _seed_two_ltlas_with_charities()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "GB-CHC-2002" in url:
            return httpx.Response(503)
        if "/grants_received/" in url:
            return httpx.Response(200, json=_grants_payload())
        return httpx.Response(200, json=_aggregate_payload())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = ThreeSixtyGivingAdapter(
            get_engine(),
            threesixtygiving_client=ThreeSixtyGivingClient(http_client=http),
            now=lambda: datetime(2026, 5, 12, tzinfo=UTC),
        )
        # Should complete without raising even though Hartlepool blows up.
        await adapter.pre_warm_for_places(["ltla24:E06000004", "ltla24:E06000001"])

        # Stockton's cache is populated.
        iv_stockton = await adapter.fetch_indicator(
            "civil_society.grants_in_last_12m_total",
            "ltla24:E06000004",
            period=None,
        )
    assert iv_stockton is not None
    assert iv_stockton.value == pytest.approx(1000.0)

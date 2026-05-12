"""Tests for the CC postcode batch resolver.

CC bulk ships ~220k UK postcodes; single-call lookup is way too slow
even at postcodes.io's 100ms p50. The resolver batches 100 postcodes
per POST to `postcodes.io/postcodes` (the bulk endpoint) and caches
the results in `geography.postcode`.

These tests build a synthetic postcodes.io bulk response and assert
the batching + caching + LTLA extraction.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from soundings.adapters.charity_commission.mapping import resolve_postcodes_to_ltlas
from soundings.adapters.postcodes_io.adapter import PostcodesIoAdapter
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_postcode_state() -> AsyncIterator[None]:
    yield
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM geography.postcode"))


def _bulk_payload(rows: list[tuple[str, str | None]]) -> dict[str, Any]:
    """postcodes.io's bulk response shape: result[].query + result[].result
    where the inner `result` is None for unknown postcodes."""
    return {
        "status": 200,
        "result": [
            {
                "query": q,
                "result": None
                if ltla is None
                else {
                    "postcode": q,
                    "codes": {
                        "admin_district": ltla,
                        "admin_county": ltla,  # simplification — real data differs
                        "admin_ward": "ward1",
                        "lsoa": "lsoa1",
                        "msoa": "msoa1",
                        "parliamentary_constituency_2024": "wm1",
                        "region": "region1",
                        "country": "E92000001",
                    },
                },
            }
            for q, ltla in rows
        ],
    }


async def _reset_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))


async def _seed_ltla_places(codes: list[str]) -> None:
    """Bulk_upsert NULLs any place_id not in `geography.place`. Production
    has the spine seeded; tests need to seed what they claim."""
    engine = get_engine()
    async with engine.begin() as conn:
        for code in codes:
            await conn.execute(
                text(
                    "INSERT INTO geography.place (id, type, code, name) "
                    "VALUES (:id, 'ltla24', :code, :name)"
                ),
                {"id": f"ltla24:{code}", "code": code, "name": f"Place {code}"},
            )


async def test_resolver_batches_to_postcodes_io_in_chunks_of_100() -> None:
    """250 postcodes → 3 POSTs, each ≤100 entries."""
    await _reset_db()
    await _seed_ltla_places([f"E0600000{i}" for i in range(6)])
    captured_bodies: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/postcodes"
        body = json.loads(request.read().decode("utf-8"))
        postcodes = body["postcodes"]
        assert len(postcodes) <= 100, "batch exceeded 100-postcode limit"
        captured_bodies.append(postcodes)
        # Echo back: every postcode resolves to ltla24:E0600000{i % 6}
        return httpx.Response(
            200,
            json=_bulk_payload([(p, f"E0600000{i % 6}") for i, p in enumerate(postcodes)]),
        )

    inputs = [f"TS18 {i:03d}" for i in range(250)]
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = PostcodesIoAdapter(get_engine(), ttl=timedelta(hours=24), http_client=http)
        result = await resolve_postcodes_to_ltlas(adapter, inputs)

    assert len(captured_bodies) == 3
    assert sum(len(b) for b in captured_bodies) == 250
    # Returned map covers every postcode (normalised — spaces stripped).
    assert len(result) == 250
    # Every result is an ltla24-flavoured place_id.
    assert all(v is not None and v.startswith("ltla24:") for v in result.values())


async def test_resolver_passes_through_unknown_postcodes_as_none() -> None:
    await _reset_db()
    await _seed_ltla_places(["E06000004"])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        return httpx.Response(
            200,
            json=_bulk_payload(
                [(p, None if i == 0 else "E06000004") for i, p in enumerate(body["postcodes"])]
            ),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = PostcodesIoAdapter(get_engine(), ttl=timedelta(hours=24), http_client=http)
        result = await resolve_postcodes_to_ltlas(adapter, ["XX0 0XX", "TS18 1AB"])

    # Unknown postcode → None entry; known one resolves.
    norm = {k.replace(" ", "").upper(): v for k, v in result.items()}
    assert norm["XX00XX"] is None
    assert norm["TS181AB"] == "ltla24:E06000004"


async def test_resolver_writes_geography_postcode_rows() -> None:
    """The bulk method also seeds geography.postcode so future
    single-postcode lookups (e.g. find_place by postcode) hit a warm
    table. Idempotent — re-resolving the same postcode UPDATEs."""
    await _reset_db()
    await _seed_ltla_places(["E06000004"])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        return httpx.Response(
            200,
            json=_bulk_payload([(p, "E06000004") for p in body["postcodes"]]),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = PostcodesIoAdapter(get_engine(), ttl=timedelta(hours=24), http_client=http)
        await resolve_postcodes_to_ltlas(adapter, ["TS18 1AB"])

    async with get_engine().connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT postcode, ltla24 FROM geography.postcode WHERE postcode = 'TS181AB'")
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].ltla24 == "ltla24:E06000004"


async def test_resolver_skips_postcodes_already_cached() -> None:
    """If a postcode is already in geography.postcode, the resolver
    short-circuits and doesn't re-fetch from postcodes.io. Crucial for
    re-runs of the monthly CC loader — we don't want to bombard
    postcodes.io with 220k requests every month."""
    await _reset_db()
    await _seed_ltla_places(["E06000004"])
    # Pre-seed the postcode cache.
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO geography.postcode "
                "(postcode, ltla24, retrieved_at) "
                "VALUES ('TS181AB', 'ltla24:E06000004', :ret)"
            ),
            {"ret": datetime.now(tz=UTC)},
        )

    api_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        api_calls += 1
        body = json.loads(request.read().decode("utf-8"))
        return httpx.Response(
            200,
            json=_bulk_payload([(p, "E06000004") for p in body["postcodes"]]),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        adapter = PostcodesIoAdapter(get_engine(), ttl=timedelta(hours=24), http_client=http)
        result = await resolve_postcodes_to_ltlas(adapter, ["TS18 1AB"])

    assert api_calls == 0, "should not have hit postcodes.io for an already-cached postcode"
    assert result["TS18 1AB"] == "ltla24:E06000004"

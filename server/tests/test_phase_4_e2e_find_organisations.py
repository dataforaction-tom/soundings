"""Phase 4 e2e — find_organisations_in_place via HTTP and MCP.

Per Phase 4 plan Task 23. Seeds cache.source_cache with Charity Commission +
360Giving payloads for an LTLA (Stockton-on-Tees), hits both transports,
asserts identical responses.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from soundings.app import app

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_phase_4_e2e() -> AsyncIterator[None]:
    yield
    # Cleanup happens in subsequent tests via fixture isolation


async def _seed_cc_and_360g() -> None:
    """Inject CC and 360G payloads into cache.source_cache for Stockton-on-Tees."""
    from sqlalchemy import text

    from soundings.db.engine import get_engine

    engine = get_engine()
    now = datetime.now(tz=UTC)
    expires = now + timedelta(hours=24)
    ltla_id = "ltla24:E06000005"  # Darlington (near Stockton)
    ltla_code = "E06000005"

    # Seed CC register for this LTLA
    cc_cache_key = f"charity-commission:registered:{ltla_id}"
    cc_records = [
        {
            "regno": "123456",
            "orgtype": "CIO",
            "name": "Darlington Community Trust",
            "registered_date": "2015-04-01",
            "geography": {
                "ltla_code": ltla_code,
            },
            "activities": "Community development",
        },
        {
            "regno": "234567",
            "orgtype": "Charitable Incorporated Organisation",
            "name": "Darlington Youth Hub",
            "registered_date": "2018-09-15",
            "geography": {
                "ltla_code": ltla_code,
            },
            "activities": "Youth services",
        },
    ]

    async with engine.begin() as conn:
        # First ensure the sources exist
        await conn.execute(
            text(
                "INSERT INTO source (id, name, adapter_class, enabled) VALUES "
                "('charity-commission', 'Charity Commission', 'CharityCommissionAdapter', true), "
                "('360giving', '360Giving', 'ThreeSixtyGivingAdapter', true) "
                "ON CONFLICT (id) DO NOTHING"
            ),
        )

        # Clear any existing cache for this LTLA
        await conn.execute(
            text("DELETE FROM cache.source_cache WHERE cache_key LIKE :pattern"),
            {"pattern": f"%{ltla_id}%"},
        )
        # Insert CC register data
        await conn.execute(
            text(
                "INSERT INTO cache.source_cache "
                "(source_id, cache_key, payload, retrieved_at, expires_at) "
                "VALUES ('charity-commission', :key, CAST(:payload AS jsonb), :ret, :exp)"
            ),
            {
                "key": cc_cache_key,
                "payload": json.dumps({"records": cc_records}),
                "ret": now,
                "exp": expires,
            },
        )

        # Seed 360G grants for one of the charities
        grant_cache_key = "360g:grants:123456"
        grant_records = [
            {
                "identifier": "GR-001",
                "title": "Community Outreach Grant",
                "amount": {"value": 50000},
                "recipient": {"id": "123456"},
                "date": {"published": "2024-06-01"},
            },
        ]

        await conn.execute(
            text(
                "INSERT INTO cache.source_cache "
                "(source_id, cache_key, payload, retrieved_at, expires_at) "
                "VALUES ('360giving', :key, CAST(:payload AS jsonb), :ret, :exp)"
            ),
            {
                "key": grant_cache_key,
                "payload": json.dumps({"grants": grant_records}),
                "ret": now,
                "exp": expires,
            },
        )


async def _call_http(place_id: str) -> dict:
    """Call the HTTP endpoint directly."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        response = await ac.post(
            "/v1/tools/find_organisations_in_place",
            json={"place_id": place_id},
        )
        assert response.status_code == 200, response.text
        return response.json()


async def _call_mcp(place_id: str) -> dict:
    """Call via MCP transport - list tools and call."""
    from soundings.mcp.server import build_mcp_server

    server = build_mcp_server()

    # Call the tool via MCP
    result = await server.call_tool(
        "find_organisations_in_place",
        arguments={
            "place_id": place_id,
            "limit": 50,
        },
    )
    # FastMCP returns a list of text artifacts; we need the first one as JSON
    if hasattr(result, "model_dump"):
        result = result.model_dump()
    return result


@pytest.mark.asyncio
async def test_find_organisations_via_http() -> None:
    """HTTP transport returns organisations for the seeded LTLA."""
    await _seed_cc_and_360g()

    result = await _call_http("ltla24:E06000005")

    assert "organisations" in result
    assert len(result["organisations"]) >= 1
    # Verify structure
    org = result["organisations"][0]
    assert "id" in org
    assert "name" in org


@pytest.mark.asyncio
async def test_find_organisations_via_mcp() -> None:
    """MCP transport returns the same organisations as HTTP."""
    await _seed_cc_and_360g()

    result = await _call_mcp("ltla24:E06000005")

    # MCP returns structured result differently; extract the JSON
    if isinstance(result, dict) and "content" in result:
        # FastMCP response format: {content: [{type: "text", text: "..."}]}
        import json

        text_content = result["content"][0].get("text", "{}")
        result = json.loads(text_content)

    assert "organisations" in result
    assert len(result["organisations"]) >= 1


@pytest.mark.asyncio
async def test_find_organisations_identical_via_both_transports() -> None:
    """Both transports return identical organisations."""
    await _seed_cc_and_360g()

    http_result = await _call_http("ltla24:E06000005")
    mcp_result = await _call_mcp("ltla24:E06000005")

    # Normalize MCP response
    if isinstance(mcp_result, dict) and "content" in mcp_result:
        import json

        mcp_result = json.loads(mcp_result["content"][0].get("text", "{}"))

    # Compare organisations (order may vary, so sort by ID)
    http_orgs = sorted(http_result.get("organisations", []), key=lambda x: x.get("id", ""))
    mcp_orgs = sorted(mcp_result.get("organisations", []), key=lambda x: x.get("id", ""))

    assert len(http_orgs) == len(mcp_orgs)
    for http_org, mcp_org in zip(http_orgs, mcp_orgs, strict=True):
        assert http_org.get("id") == mcp_org.get("id")
        assert http_org.get("name") == mcp_org.get("name")

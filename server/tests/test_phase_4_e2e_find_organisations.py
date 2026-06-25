"""Phase 4 e2e — find_organisations_in_place via HTTP and MCP.

Seeds a place plus two Charity Commission organisations registered there
(data.organisation, the loader-populated path the tool reads), hits both
transports, and asserts they return the same organisations.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from soundings.app import app

pytestmark = pytest.mark.integration

PLACE_ID = "ltla24:E06000005"
ORG_IDS = ("GB-CHC-1011121", "GB-CHC-1011122")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_phase_4_e2e() -> AsyncIterator[None]:
    yield
    # Remove everything this module seeds, in FK-safe order, so it can't leak
    # into other integration tests (some of which DELETE FROM geography.place).
    from sqlalchemy import text

    from soundings.db.engine import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM data.organisation_operates_in WHERE place_id = :pid"),
            {"pid": PLACE_ID},
        )
        await conn.execute(
            text("DELETE FROM data.organisation WHERE registered_address_place_id = :pid"),
            {"pid": PLACE_ID},
        )
        await conn.execute(
            text("DELETE FROM geography.place WHERE id = :pid"),
            {"pid": PLACE_ID},
        )


async def _seed_place_and_organisations() -> None:
    """Seed a place and two organisations registered there.

    Mirrors what find_organisations_in_place actually reads for England/Wales:
    data.organisation rows joined to the place via registered_address_place_id
    (the loader-populated path), not the cache.
    """
    from sqlalchemy import text

    from soundings.db.engine import get_engine

    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        # catalogue.source — FK target for data.organisation.source_id.
        await conn.execute(
            text(
                "INSERT INTO catalogue.source "
                "(id, label, publisher, licence, mode, rate_limit) VALUES "
                "('charity_commission', 'Charity Commission', 'Charity Commission', "
                "'OGL-3.0', 'loader', '{}'::jsonb) ON CONFLICT (id) DO NOTHING"
            ),
        )
        # geography.place — FK target for registered_address_place_id.
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES (:pid, 'ltla24', 'E06000005', 'Darlington') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"pid": PLACE_ID},
        )
        # data.organisation — the rows the tool returns.
        await conn.execute(
            text(
                "INSERT INTO data.organisation "
                "(id, name, classification, registered_address_place_id, "
                " source_id, retrieved_at, raw) VALUES "
                "(:id1, 'Darlington Community Trust', "
                " ARRAY['Community development']::varchar[], :pid, "
                " 'charity_commission', :now, '{}'::jsonb), "
                "(:id2, 'Darlington Youth Hub', "
                " ARRAY['Youth services']::varchar[], :pid, "
                " 'charity_commission', :now, '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id1": ORG_IDS[0], "id2": ORG_IDS[1], "pid": PLACE_ID, "now": now},
        )


async def _call_http(place_id: str) -> dict:
    """Call the HTTP endpoint. The lifespan context populates app.state
    (orchestrator, engine, …) — ASGITransport alone does not run it."""
    async with app.router.lifespan_context(app):
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
    """Call via the MCP transport. build_mcp_server needs the populated
    app.state, so build and invoke it inside the lifespan context."""
    from soundings.mcp.server import build_mcp_server

    async with app.router.lifespan_context(app):
        server = build_mcp_server(app.state)
        result = await server.call_tool(
            "find_organisations_in_place",
            {"place_id": place_id, "limit": 50},
        )
    # FastMCP returns a tuple of (content, structured_payload); locate the dict
    # carrying the organisations list.
    if isinstance(result, tuple):
        for part in result:
            if isinstance(part, dict) and "organisations" in part:
                return part
        if result and isinstance(result[-1], dict):
            return result[-1]
    if isinstance(result, dict):
        return result
    raise AssertionError(f"unexpected MCP result shape: {type(result)}")


@pytest.mark.asyncio
async def test_find_organisations_via_http() -> None:
    """HTTP transport returns organisations for the seeded LTLA."""
    await _seed_place_and_organisations()

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
    await _seed_place_and_organisations()

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
    await _seed_place_and_organisations()

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

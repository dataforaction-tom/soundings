"""Phase 1 acceptance test.

End-to-end through both transports for the same input:
  HTTP: POST /v1/tools/get_indicators
  MCP : call the registered FastMCP tool directly.

Both must return the same indicator values with the same provenance.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from soundings.app import app
from soundings.db.engine import get_engine
from soundings.mcp.server import build_mcp_server

pytestmark = pytest.mark.integration


async def _seed() -> None:
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.loader_run"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:E06000004', 'ltla24', 'E06000004', 'Stockton-on-Tees')"
            )
        )
        for source_id in ("ons.mid_year_estimates", "mhclg.imd2025"):
            await conn.execute(
                text(
                    "INSERT INTO data.loader_run "
                    "(id, source_id, started_at, finished_at, status, rows_written) "
                    "VALUES (:id, :sid, :s, :f, 'ok', 1)"
                ),
                {
                    "id": uuid.uuid4(),
                    "sid": source_id,
                    "s": now - timedelta(minutes=5),
                    "f": now,
                },
            )
        await conn.execute(
            text(
                "INSERT INTO data.indicator_value "
                "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) VALUES "
                "('ltla24:E06000004', 'population.total', '2024', 200000, 'ons.mid_year_estimates', :ret, '[]'::jsonb), "
                "('ltla24:E06000004', 'deprivation.imd.score', '2025', 24.0, 'mhclg.imd2025', :ret, '[]'::jsonb)"
            ),
            {"ret": now},
        )


async def test_phase_1_get_indicators_via_http() -> None:
    await _seed()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/v1/tools/get_indicators",
                json={
                    "place_id": "ltla24:E06000004",
                    "indicators": ["population.total", "deprivation.imd.score"],
                },
            )
    assert response.status_code == 200
    body = response.json()
    by_key = {r["indicator"]: r for r in body["results"]}
    assert by_key["population.total"]["value"] == 200000
    assert by_key["deprivation.imd.score"]["value"] == 24.0
    # Every value carries provenance with non-null cache_status.
    assert all(r["source"]["cache_status"] in ("live", "cached", "stale") for r in body["results"])
    # Sources de-duplicated by (source_id, minute).
    assert len({s["source_id"] for s in body["sources"]}) == 2


async def test_phase_1_get_indicators_via_mcp_tool_call() -> None:
    await _seed()
    async with app.router.lifespan_context(app):
        # Reuse the already-built MCP server bound to app.state.
        mcp = build_mcp_server(state=app.state)
        # FastMCP exposes the underlying registered tools via call_tool().
        result = await mcp.call_tool(
            "get_indicators",
            {
                "place_id": "ltla24:E06000004",
                "indicators": ["population.total", "deprivation.imd.score"],
            },
        )
    # FastMCP returns a tuple of (content, metadata) or similar; locate the
    # structured payload.
    payload = None
    if isinstance(result, tuple):
        for part in result:
            if isinstance(part, dict) and "results" in part:
                payload = part
                break
        if payload is None and result and isinstance(result[-1], dict):
            payload = result[-1]
    elif isinstance(result, dict):
        payload = result

    assert payload is not None, f"unexpected MCP result shape: {type(result)}"
    by_key = {r["indicator"]: r for r in payload["results"]}
    assert by_key["population.total"]["value"] == 200000
    assert by_key["deprivation.imd.score"]["value"] == 24.0

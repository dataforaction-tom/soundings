"""End-to-end test for compare_places via both transports.

Phase 3 Task 31. Confirms the same tool implementation reaches the same
result whether invoked via POST /v1/tools/compare_places or via the
FastMCP `compare_places` tool call.
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


async def _seed_three_ltlas_with_population() -> None:
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
                "INSERT INTO data.loader_run "
                "(id, source_id, started_at, finished_at, status, rows_written) "
                "VALUES (:id, 'ons.mid_year_estimates', :s, :f, 'ok', 3)"
            ),
            {"id": uuid.uuid4(), "s": now - timedelta(minutes=5), "f": now},
        )
        for i, (code, name) in enumerate(
            [
                ("E06000001", "Hartlepool"),
                ("E06000004", "Stockton"),
                ("E06000005", "Darlington"),
            ],
            start=1,
        ):
            await conn.execute(
                text(
                    "INSERT INTO geography.place (id, type, code, name) "
                    "VALUES (:id, 'ltla24', :code, :name)"
                ),
                {"id": f"ltla24:{code}", "code": code, "name": name},
            )
            await conn.execute(
                text(
                    "INSERT INTO data.indicator_value "
                    "(place_id, indicator_key, period, value, source_id, "
                    "retrieved_at, caveats) VALUES "
                    "(:pid, 'population.total', '2024', :val, "
                    "'ons.mid_year_estimates', :ret, '[]'::jsonb)"
                ),
                {"pid": f"ltla24:{code}", "val": i * 100, "ret": now},
            )


async def test_compare_places_via_http_returns_full_universe_ranks() -> None:
    await _seed_three_ltlas_with_population()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/v1/tools/compare_places",
                json={
                    "place_ids": ["ltla24:E06000004"],
                    "indicators": ["population.total"],
                    "comparison_basis": "percentile",
                },
            )

    assert response.status_code == 200, response.text
    body = response.json()
    cv = body["results"][0]["values"][0]
    assert cv["value"] == 200
    assert cv["rank"] == 2
    assert cv["percentile"] == pytest.approx(50.0)


async def test_compare_places_via_mcp_tool_call_matches_http() -> None:
    await _seed_three_ltlas_with_population()
    async with app.router.lifespan_context(app):
        mcp = build_mcp_server(state=app.state)
        result = await mcp.call_tool(
            "compare_places",
            {
                "place_ids": ["ltla24:E06000004"],
                "indicators": ["population.total"],
                "comparison_basis": "percentile",
            },
        )

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
    cv = payload["results"][0]["values"][0]
    assert cv["place_id"] == "ltla24:E06000004"
    assert cv["value"] == 200
    assert cv["rank"] == 2
    assert cv["percentile"] == pytest.approx(50.0)

"""End-to-end test for get_trend via both transports.

Phase 3 Task 35. Confirms the same tool implementation reaches the same
result whether invoked via POST /v1/tools/get_trend or via the FastMCP
`get_trend` tool call.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from soundings.app import app
from soundings.db.engine import get_engine
from soundings.mcp.server import build_mcp_server

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_trend_point() -> AsyncIterator[None]:
    yield
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))


async def _seed_stockton_trend() -> None:
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:E06000004', 'ltla24', 'E06000004', 'Stockton-on-Tees')"
            )
        )
        for period, value in [("2022", 195000.0), ("2023", 196500.0), ("2024", 198000.0)]:
            await conn.execute(
                text(
                    "INSERT INTO data.trend_point "
                    "(place_id, indicator_key, period, value, revised, "
                    "source_id, retrieved_at) "
                    "VALUES ('ltla24:E06000004', 'population.total', :p, :v, "
                    "false, 'ons.mid_year_estimates', :ret)"
                ),
                {"p": period, "v": value, "ret": now},
            )


async def test_get_trend_via_http() -> None:
    await _seed_stockton_trend()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/v1/tools/get_trend",
                json={
                    "place_id": "ltla24:E06000004",
                    "indicator": "population.total",
                    "period_from": "2023",
                },
            )

    assert response.status_code == 200, response.text
    body = response.json()
    trend = body["trend"]
    assert trend is not None
    assert [p["period"] for p in trend["points"]] == ["2023", "2024"]


async def test_get_trend_via_mcp_matches_http() -> None:
    await _seed_stockton_trend()
    async with app.router.lifespan_context(app):
        mcp = build_mcp_server(state=app.state)
        result = await mcp.call_tool(
            "get_trend",
            {
                "place_id": "ltla24:E06000004",
                "indicator": "population.total",
            },
        )

    payload = None
    if isinstance(result, tuple):
        for part in result:
            if isinstance(part, dict) and "trend" in part:
                payload = part
                break
        if payload is None and result and isinstance(result[-1], dict):
            payload = result[-1]
    elif isinstance(result, dict):
        payload = result

    assert payload is not None, f"unexpected MCP result shape: {type(result)}"
    trend = payload["trend"]
    assert trend is not None
    assert [p["period"] for p in trend["points"]] == ["2022", "2023", "2024"]
    assert trend["points"][-1]["value"] == 198000.0

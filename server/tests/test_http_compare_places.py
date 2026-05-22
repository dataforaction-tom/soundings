"""HTTP route tests for POST /v1/tools/compare_places."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from soundings.app import app
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_three_ltlas_with_population() -> None:
    """Three LTLAs with population values 100, 200, 300. Lets the route
    answer compare_places(percentile) end-to-end through the real
    AdapterRegistry registered in app.py."""
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.loader_run"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        run = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO data.loader_run "
                "(id, source_id, started_at, finished_at, status, rows_written) "
                "VALUES (:id, 'ons.mid_year_estimates', :s, :f, 'ok', 3)"
            ),
            {"id": run, "s": now - timedelta(minutes=5), "f": now},
        )
        for i, (code, name) in enumerate(
            [("E06000001", "Hartlepool"), ("E06000004", "Stockton"), ("E06000005", "Darlington")],
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


async def test_post_compare_places_returns_ranks_against_peer_universe() -> None:
    await _seed_three_ltlas_with_population()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/v1/tools/compare_places",
                json={
                    "place_ids": ["ltla24:E06000004", "ltla24:E06000005"],
                    "indicators": ["population.total"],
                    "comparison_basis": "percentile",
                },
            )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["results"]) == 1
    comparison = body["results"][0]
    assert comparison["indicator"] == "population.total"
    assert comparison["period"] == "2024"

    values_by_pid = {v["place_id"]: v for v in comparison["values"]}
    # Stockton has value 200 — median of 3 → rank 2, percentile 50.
    stockton = values_by_pid["ltla24:E06000004"]
    assert stockton["value"] == 200
    assert stockton["rank"] == 2
    assert stockton["percentile"] == pytest.approx(50.0)
    # Darlington has value 300 — top of 3 → rank 1, percentile 100.
    darlington = values_by_pid["ltla24:E06000005"]
    assert darlington["rank"] == 1
    assert darlington["percentile"] == pytest.approx(100.0)


async def test_list_tools_advertises_compare_places() -> None:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/v1/tools")
    assert response.status_code == 200
    names = [t["name"] for t in response.json()["tools"]]
    assert "compare_places" in names

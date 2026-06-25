"""HTTP route tests for GET /v1/place/{place_id}/geometry and peers/geometry."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from soundings.app import app
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration

# Simple triangle WKT geometries (SRID 4326 not strictly needed for tests,
# ST_GeomFromEWKT with explicit SRID ensures the column accepts them).
_TRIANGLE_A = "SRID=4326;MULTIPOLYGON(((0 0,0 1,1 0,0 0)))"
_TRIANGLE_B = "SRID=4326;MULTIPOLYGON(((2 2,2 3,3 2,2 2)))"


async def _seed_places_with_geometry() -> None:
    """Three LTLAs — two with geometry, one without — plus indicator values."""
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
        # Place with geometry
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name, geom) "
                "VALUES (:id, 'ltla24', :code, :name, ST_GeomFromEWKT(:geom))"
            ),
            {
                "id": "ltla24:E06000001",
                "code": "E06000001",
                "name": "Hartlepool",
                "geom": _TRIANGLE_A,
            },
        )
        # Peer with geometry
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name, geom) "
                "VALUES (:id, 'ltla24', :code, :name, ST_GeomFromEWKT(:geom))"
            ),
            {
                "id": "ltla24:E06000004",
                "code": "E06000004",
                "name": "Stockton",
                "geom": _TRIANGLE_B,
            },
        )
        # Peer without geometry
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES (:id, 'ltla24', :code, :name)"
            ),
            {"id": "ltla24:E06000005", "code": "E06000005", "name": "Darlington"},
        )
        # Indicator values for all three places
        for pid, val in [
            ("ltla24:E06000001", 100),
            ("ltla24:E06000004", 200),
            ("ltla24:E06000005", 300),
        ]:
            await conn.execute(
                text(
                    "INSERT INTO data.indicator_value "
                    "(place_id, indicator_key, period, value, source_id, "
                    "retrieved_at, caveats) VALUES "
                    "(:pid, 'population.total', '2024', :val, "
                    "'ons.mid_year_estimates', :ret, '[]'::jsonb)"
                ),
                {"pid": pid, "val": val, "ret": now},
            )


# ---------------------------------------------------------------------------
# Task 1: GET /v1/place/{place_id}/geometry
# ---------------------------------------------------------------------------


async def test_get_place_geometry_returns_feature() -> None:
    await _seed_places_with_geometry()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/v1/place/ltla24:E06000001/geometry")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "Feature"
    assert body["properties"]["id"] == "ltla24:E06000001"
    assert body["properties"]["name"] == "Hartlepool"
    assert body["properties"]["type"] == "ltla24"
    assert body["geometry"] is not None
    assert body["geometry"]["type"] == "MultiPolygon"


async def test_get_place_geometry_404_for_missing_place() -> None:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/v1/place/nonexistent/geometry")
    assert response.status_code == 404


async def test_get_place_geometry_null_for_no_geom() -> None:
    await _seed_places_with_geometry()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/v1/place/ltla24:E06000005/geometry")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "Feature"
    assert body["geometry"] is None
    assert body["properties"]["id"] == "ltla24:E06000005"
    assert body["properties"]["name"] == "Darlington"


# ---------------------------------------------------------------------------
# Task 2: GET /v1/place/{place_id}/peers/geometry
# ---------------------------------------------------------------------------


async def test_get_peers_geometry_returns_feature_collection() -> None:
    await _seed_places_with_geometry()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/v1/place/ltla24:E06000001/peers/geometry",
                params={"indicator": "population.total", "period": "2024"},
            )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "FeatureCollection"
    features = body["features"]
    # Two peers (excluding the place itself)
    assert len(features) == 2
    ids = {f["properties"]["id"] for f in features}
    assert ids == {"ltla24:E06000004", "ltla24:E06000005"}
    # Stockton has geom, Darlington doesn't
    stockton = next(f for f in features if f["properties"]["id"] == "ltla24:E06000004")
    assert stockton["geometry"] is not None
    assert stockton["geometry"]["type"] == "MultiPolygon"
    assert stockton["properties"]["value"] == 200
    darlington = next(f for f in features if f["properties"]["id"] == "ltla24:E06000005")
    assert darlington["geometry"] is None
    assert darlington["properties"]["value"] == 300


async def test_get_peers_geometry_percentile() -> None:
    """Values: Stockton 200, Darlington 300. n=2.
    Darlington rank 1 (highest) → percentile 100.
    Stockton rank 2 → percentile 0."""
    await _seed_places_with_geometry()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/v1/place/ltla24:E06000001/peers/geometry",
                params={"indicator": "population.total", "period": "2024"},
            )
    assert response.status_code == 200, response.text
    body = response.json()
    by_id = {f["properties"]["id"]: f["properties"] for f in body["features"]}
    assert by_id["ltla24:E06000005"]["percentile"] == pytest.approx(100.0)
    assert by_id["ltla24:E06000004"]["percentile"] == pytest.approx(0.0)


async def test_get_peers_geometry_404_for_missing_place() -> None:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/v1/place/nonexistent/peers/geometry",
                params={"indicator": "population.total", "period": "2024"},
            )
    assert response.status_code == 404

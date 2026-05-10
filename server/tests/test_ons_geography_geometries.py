import httpx
import pytest
from sqlalchemy import select, text

from soundings.adapters.ons_geography.endpoints import OgpLayer
from soundings.adapters.ons_geography.geometries_loader import (
    OnsGeographyGeometriesLoader,
)
from soundings.db.engine import get_engine
from soundings.db.models.geography import Place

pytestmark = pytest.mark.integration


SQUARE_POLYGON_GEOJSON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-1.32, 54.56],
            [-1.30, 54.56],
            [-1.30, 54.58],
            [-1.32, 54.58],
            [-1.32, 54.56],
        ]
    ],
}


async def _seed_place(place_id: str, place_type: str, code: str, name: str) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            Place.__table__.insert().values(
                id=place_id, type=place_type, code=code, name=name
            )
        )


async def test_geometries_loader_updates_place_geom() -> None:
    engine = get_engine()
    await _seed_place("ltla24:E07000223", "ltla24", "E07000223", "Stockton-on-Tees")

    layer = OgpLayer(
        place_type="ltla24",
        code_field="LAD24CD",
        name_field="LAD24NM",
        service_name="test_ltla_layer",
    )

    body = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "LAD24CD": "E07000223",
                    "LAD24NM": "Stockton-on-Tees",
                },
                "geometry": SQUARE_POLYGON_GEOJSON,
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        loader = OnsGeographyGeometriesLoader(
            engine, http_client=client, layers={"ltla24": layer}
        )
        result = await loader.load()

    assert result.rows_written == 1

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, ST_IsValid(geom) AS valid, ST_GeometryType(geom) AS gt "
                    "FROM geography.place WHERE id = 'ltla24:E07000223'"
                )
            )
        ).first()
    assert row is not None
    assert row.valid is True
    assert row.gt == "ST_MultiPolygon"


async def test_geometries_loader_skips_unknown_places() -> None:
    engine = get_engine()
    await _seed_place(
        "ltla24:E07000223", "ltla24", "E07000223", "Stockton-on-Tees"
    )

    layer = OgpLayer("ltla24", "LAD24CD", "LAD24NM", "test_ltla_layer")
    body = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"LAD24CD": "E07000999", "LAD24NM": "Made-up"},
                "geometry": SQUARE_POLYGON_GEOJSON,
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        loader = OnsGeographyGeometriesLoader(
            engine, http_client=client, layers={"ltla24": layer}
        )
        result = await loader.load()

    assert result.rows_written == 0
    async with engine.connect() as conn:
        existing = (
            await conn.execute(
                select(Place.id).where(Place.id == "ltla24:E07000999")
            )
        ).scalar_one_or_none()
    assert existing is None

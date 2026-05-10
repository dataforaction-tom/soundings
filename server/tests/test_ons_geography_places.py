import httpx
import pytest
from sqlalchemy import select, text

from soundings.adapters.ons_geography.endpoints import OgpLayer
from soundings.adapters.ons_geography.places_loader import OnsGeographyPlacesLoader
from soundings.db.engine import get_engine
from soundings.db.models.geography import Place

pytestmark = pytest.mark.integration


def _ogp_response(features: list[dict[str, str]]) -> dict[str, list[dict[str, dict[str, str]]]]:
    return {"features": [{"attributes": a} for a in features]}


async def test_places_loader_upserts_place_rows() -> None:
    engine = get_engine()

    # Clean slate.
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place WHERE type = 'lsoa21'"))

    layer = OgpLayer(
        place_type="lsoa21",
        code_field="LSOA21CD",
        name_field="LSOA21NM",
        service_name="test_lsoa_layer",
    )

    fake_features = [
        {"LSOA21CD": "E01000001", "LSOA21NM": "City of London 001A"},
        {"LSOA21CD": "E01000002", "LSOA21NM": "City of London 001B"},
        {"LSOA21CD": "E01012018", "LSOA21NM": "Stockton-on-Tees 010A"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        # OGP returns one page; loader stops because len < PAGE_SIZE.
        return httpx.Response(200, json=_ogp_response(fake_features))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        loader = OnsGeographyPlacesLoader(engine, http_client=client, layers={"lsoa21": layer})
        result = await loader.load()

    assert result.rows_written == 3

    async with engine.connect() as conn:
        rows = (
            await conn.execute(select(Place.id, Place.name).where(Place.type == "lsoa21"))
        ).all()
    by_id = {row.id: row.name for row in rows}
    assert by_id["lsoa21:E01000001"] == "City of London 001A"
    assert by_id["lsoa21:E01012018"] == "Stockton-on-Tees 010A"


async def test_places_loader_is_idempotent() -> None:
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place WHERE type = 'lsoa21'"))

    layer = OgpLayer("lsoa21", "LSOA21CD", "LSOA21NM", "test_lsoa_layer")
    features = [{"LSOA21CD": "E01000001", "LSOA21NM": "Renamed area"}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_ogp_response(features))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        loader = OnsGeographyPlacesLoader(engine, http_client=client, layers={"lsoa21": layer})
        await loader.load()
        await loader.load()  # second call must not fail or duplicate.

    async with engine.connect() as conn:
        rows = (
            await conn.execute(select(Place.id, Place.name).where(Place.type == "lsoa21"))
        ).all()
    assert len(rows) == 1
    assert rows[0].name == "Renamed area"

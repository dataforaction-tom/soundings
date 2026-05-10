"""Phase 0 acceptance test.

Stitches the geography spine together end-to-end:
  postcode -> postcodes.io adapter -> postcode cache -> place rows ->
  containing places (via hierarchy AND via PostGIS).

Uses httpx.MockTransport for the postcodes.io call and pre-seeded
fixtures for the place spine. The corresponding live test against
the real ONS + postcodes.io APIs is intentionally separate (a
nightly @pytest.mark.live job, see CI in Task 37).
"""

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import text

from soundings.adapters.postcodes_io.adapter import PostcodesIoAdapter
from soundings.db.engine import get_engine
from soundings.db.models.geography import Place
from soundings.geography.service import GeographyService

pytestmark = pytest.mark.integration


SAMPLE_RESPONSE = {
    "status": 200,
    "result": {
        "postcode": "TS18 1AB",
        "codes": {
            "admin_district": "E06000004",
            "admin_county": "E06000004",
            "admin_ward": "E05014203",
            "parliamentary_constituency_2024": "E14001599",
            "country": "E92000001",
            "lsoa": "E01012018",
            "msoa": "E02002565",
            "region": "E12000001",
        },
    },
}

PLACE_FIXTURES = [
    ("lsoa21:E01012018", "lsoa21", "E01012018", "Stockton-on-Tees 010A"),
    ("msoa21:E02002565", "msoa21", "E02002565", "Stockton-on-Tees 010"),
    ("ltla24:E06000004", "ltla24", "E06000004", "Stockton-on-Tees"),
    ("utla24:E06000004", "utla24", "E06000004", "Stockton-on-Tees"),
    ("ward24:E05014203", "ward24", "E05014203", "Norton North"),
    (
        "westminster_constituency_24:E14001599",
        "westminster_constituency_24",
        "E14001599",
        "Stockton North",
    ),
    ("region:E12000001", "region", "E12000001", "North East"),
    ("country:E92000001", "country", "E92000001", "England"),
]


HIERARCHY_EDGES = [
    ("lsoa21:E01012018", "msoa21:E02002565"),
    ("lsoa21:E01012018", "ltla24:E06000004"),
    ("lsoa21:E01012018", "utla24:E06000004"),
    ("lsoa21:E01012018", "ward24:E05014203"),
    ("lsoa21:E01012018", "westminster_constituency_24:E14001599"),
    ("lsoa21:E01012018", "region:E12000001"),
    ("lsoa21:E01012018", "country:E92000001"),
    ("msoa21:E02002565", "ltla24:E06000004"),
    ("msoa21:E02002565", "region:E12000001"),
    ("msoa21:E02002565", "country:E92000001"),
    ("ltla24:E06000004", "region:E12000001"),
    ("ltla24:E06000004", "country:E92000001"),
    ("region:E12000001", "country:E92000001"),
]


async def _seed_full_spine() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        for place_id, place_type, code, name in PLACE_FIXTURES:
            await conn.execute(
                Place.__table__.insert().values(
                    id=place_id, type=place_type, code=code, name=name
                )
            )
        for child, parent in HIERARCHY_EDGES:
            await conn.execute(
                text(
                    "INSERT INTO geography.place_hierarchy (child_id, parent_id) "
                    "VALUES (:c, :p) ON CONFLICT DO NOTHING"
                ),
                {"c": child, "p": parent},
            )
        # Plant a polygon for the LTLA so the point-in-polygon path works.
        await conn.execute(
            text(
                "UPDATE geography.place SET geom = ST_Multi(ST_GeomFromGeoJSON(:gj)) "
                "WHERE id = 'ltla24:E06000004'"
            ),
            {
                "gj": (
                    '{"type":"Polygon","coordinates":[[[-1.32,54.56],[-1.30,54.56],'
                    "[-1.30,54.58],[-1.32,54.58],[-1.32,54.56]]]}"
                )
            },
        )


def _make_service(engine: object) -> GeographyService:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = PostcodesIoAdapter(engine, ttl=timedelta(hours=720), http_client=client)
    return GeographyService(engine, adapter)


async def test_postcode_resolves_to_all_geographies() -> None:
    engine = get_engine()
    await _seed_full_spine()
    svc = _make_service(engine)

    result = await svc.find_place_by_postcode("TS18 1AB")
    assert result is not None
    for level in (
        "lsoa21",
        "msoa21",
        "ltla24",
        "utla24",
        "ward24",
        "westminster_constituency_24",
        "region",
        "country",
    ):
        assert level in result, f"missing {level} in postcode resolution"
    assert result["ltla24"].name == "Stockton-on-Tees"
    assert result["utla24"].name == "Stockton-on-Tees"
    assert result["region"].name == "North East"
    assert result["country"].name == "England"


async def test_hierarchy_and_geometry_agree() -> None:
    engine = get_engine()
    await _seed_full_spine()
    svc = _make_service(engine)

    via_hierarchy = await svc.find_containing_places("lsoa21:E01012018")
    via_geom = await svc.find_containing_places_by_point(54.57, -1.31)

    hier_ltla = next((p for p in via_hierarchy if p.type == "ltla24"), None)
    geom_ltla = next((p for p in via_geom if p.type == "ltla24"), None)
    assert hier_ltla is not None
    assert geom_ltla is not None
    assert hier_ltla.id == geom_ltla.id

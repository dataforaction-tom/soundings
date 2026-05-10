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


async def _seed_places() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        for place_id, place_type, code, name in PLACE_FIXTURES:
            await conn.execute(
                Place.__table__.insert().values(id=place_id, type=place_type, code=code, name=name)
            )


async def test_find_place_by_postcode_returns_all_levels() -> None:
    engine = get_engine()
    await _seed_places()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = PostcodesIoAdapter(engine, ttl=timedelta(hours=720), http_client=client)
        svc = GeographyService(engine, adapter)
        result = await svc.find_place_by_postcode("TS18 1AB")

    assert result is not None
    assert {
        "lsoa21",
        "msoa21",
        "ltla24",
        "utla24",
        "ward24",
        "westminster_constituency_24",
        "region",
        "country",
    } <= set(result.keys())
    assert result["ltla24"].name == "Stockton-on-Tees"
    assert result["country"].name == "England"


async def test_find_place_by_name_returns_top_match() -> None:
    engine = get_engine()
    await _seed_places()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = PostcodesIoAdapter(engine, ttl=timedelta(hours=720), http_client=client)
        svc = GeographyService(engine, adapter)
        matches = await svc.find_place_by_name("stockton", geography_types=["ltla24"])
    assert len(matches) >= 1
    assert matches[0].place.id == "ltla24:E06000004"
    assert 0 < matches[0].confidence <= 1.0


async def test_find_containing_places_via_hierarchy() -> None:
    engine = get_engine()
    await _seed_places()
    # Seed hierarchy: lsoa -> msoa -> ltla -> region -> country
    async with engine.begin() as conn:
        edges = [
            ("lsoa21:E01012018", "msoa21:E02002565"),
            ("lsoa21:E01012018", "ltla24:E06000004"),
            ("lsoa21:E01012018", "region:E12000001"),
            ("lsoa21:E01012018", "country:E92000001"),
            ("msoa21:E02002565", "ltla24:E06000004"),
            ("msoa21:E02002565", "region:E12000001"),
            ("msoa21:E02002565", "country:E92000001"),
            ("ltla24:E06000004", "region:E12000001"),
            ("ltla24:E06000004", "country:E92000001"),
            ("region:E12000001", "country:E92000001"),
        ]
        for child, parent in edges:
            await conn.execute(
                text(
                    "INSERT INTO geography.place_hierarchy (child_id, parent_id) "
                    "VALUES (:c, :p) ON CONFLICT DO NOTHING"
                ),
                {"c": child, "p": parent},
            )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = PostcodesIoAdapter(engine, ttl=timedelta(hours=720), http_client=client)
        svc = GeographyService(engine, adapter)
        ancestors = await svc.find_containing_places("lsoa21:E01012018")

    types = {p.type for p in ancestors}
    assert "msoa21" in types
    assert "ltla24" in types
    assert "region" in types
    assert "country" in types


async def test_find_containing_places_by_point_returns_polygon_match() -> None:
    engine = get_engine()
    await _seed_places()
    # Plant a polygon that covers (54.57, -1.31) on the LTLA row.
    async with engine.begin() as conn:
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

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = PostcodesIoAdapter(engine, ttl=timedelta(hours=720), http_client=client)
        svc = GeographyService(engine, adapter)
        hits = await svc.find_containing_places_by_point(54.57, -1.31, types=["ltla24"])

    assert any(p.id == "ltla24:E06000004" for p in hits)

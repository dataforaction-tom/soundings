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
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        for place_id, place_type, code, name in PLACE_FIXTURES:
            await conn.execute(
                Place.__table__.insert().values(
                    id=place_id, type=place_type, code=code, name=name
                )
            )


async def test_find_place_by_postcode_returns_all_levels() -> None:
    engine = get_engine()
    await _seed_places()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = PostcodesIoAdapter(
            engine, ttl=timedelta(hours=720), http_client=client
        )
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

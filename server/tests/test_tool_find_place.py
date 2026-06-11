from datetime import timedelta

import httpx
import pytest
from sqlalchemy import text

from soundings.adapters.postcodes_io.adapter import PostcodesIoAdapter
from soundings.db.engine import get_engine
from soundings.geography.service import GeographyService
from soundings.tools.find_place import FindPlaceInput, find_place

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
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        for pid, ptype, code, name in PLACE_FIXTURES:
            await conn.execute(
                text("INSERT INTO geography.place (id, type, code, name) VALUES (:id, :t, :c, :n)"),
                {"id": pid, "t": ptype, "c": code, "n": name},
            )


def _build_service(engine) -> GeographyService:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = PostcodesIoAdapter(engine, ttl=timedelta(hours=720), http_client=client)
    return GeographyService(engine, adapter)


async def test_find_place_with_postcode_input() -> None:
    engine = get_engine()
    await _seed_places()
    svc = _build_service(engine)

    result = await find_place(FindPlaceInput(query="TS18 1AB"), svc)
    ids = {m.id for m in result.matches}
    assert "lsoa21:E01012018" in ids
    assert "ltla24:E06000004" in ids
    assert all(m.confidence == 1.0 for m in result.matches)


async def test_find_place_with_name_input_returns_ranked_matches() -> None:
    engine = get_engine()
    await _seed_places()
    svc = _build_service(engine)

    result = await find_place(
        FindPlaceInput(query="stockton", geography_types=["ltla24"]),
        svc,
    )
    assert len(result.matches) >= 1
    assert result.matches[0].id == "ltla24:E06000004"
    assert 0.0 < result.matches[0].confidence <= 1.0


async def test_find_place_name_ranks_ltla_above_region_for_same_name() -> None:
    """When several places share a similar name, the deepest level wins."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        for pid, ptype, code, name in [
            ("region:E12000001", "region", "E12000001", "Newcastle Region"),
            ("utla24:E08000021", "utla24", "E08000021", "Newcastle upon Tyne"),
            ("ltla24:E08000021", "ltla24", "E08000021", "Newcastle upon Tyne"),
        ]:
            await conn.execute(
                text("INSERT INTO geography.place (id, type, code, name) VALUES (:id, :t, :c, :n)"),
                {"id": pid, "t": ptype, "c": code, "n": name},
            )
    svc = _build_service(engine)
    result = await find_place(FindPlaceInput(query="Newcastle upon Tyne"), svc)
    assert result.matches[0].type == "ltla24"
    assert result.matches[0].confidence > 0.8


async def test_find_place_handles_unknown_postcode_gracefully() -> None:
    engine = get_engine()
    await _seed_places()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"status": 404})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = PostcodesIoAdapter(engine, ttl=timedelta(hours=720), http_client=client)
        svc = GeographyService(engine, adapter)
        result = await find_place(FindPlaceInput(query="ZZ99 9ZZ"), svc)
    assert result.matches == []

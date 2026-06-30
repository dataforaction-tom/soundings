from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select, text

from soundings.adapters.postcodes_io.adapter import PostcodesIoAdapter
from soundings.db.engine import get_engine
from soundings.db.models.geography import Place, Postcode

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


async def _seed_places(exclude_types: set[str] | None = None) -> None:
    exclude_types = exclude_types or set()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place"))
        # ltla24 and utla24 share the same code in unitary authorities;
        # only insert one row per (type, code, valid_from) — they're distinct
        # by type so the unique constraint allows both.
        seen: set[str] = set()
        for place_id, place_type, code, name in PLACE_FIXTURES:
            if place_id in seen or place_type in exclude_types:
                continue
            seen.add(place_id)
            await conn.execute(
                Place.__table__.insert().values(id=place_id, type=place_type, code=code, name=name)
            )


async def test_upsert_postcode_writes_canonical_row() -> None:
    engine = get_engine()
    await _seed_places()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = PostcodesIoAdapter(engine, ttl=timedelta(hours=720), http_client=client)
        row = await adapter.upsert_postcode("TS18 1AB")

    assert row is not None
    assert row.postcode == "TS181AB"
    async with engine.connect() as conn:
        stored = (
            await conn.execute(select(Postcode).where(Postcode.postcode == "TS181AB"))
        ).first()
    assert stored is not None
    assert stored.lsoa21 == "lsoa21:E01012018"
    assert stored.ltla24 == "ltla24:E06000004"
    assert stored.country == "country:E92000001"


async def test_upsert_postcode_fk_safe_when_msoa_place_missing() -> None:
    """A partial geography spine (this project drops the MSOA layer) must not
    FK-fail the single-postcode upsert. The unseeded msoa21 reference is NULLed
    out and the rest of the row is written. Reproduces the DL5 6LA 500."""
    engine = get_engine()
    await _seed_places(exclude_types={"msoa21"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = PostcodesIoAdapter(engine, ttl=timedelta(hours=720), http_client=client)
        row = await adapter.upsert_postcode("TS18 1AB")

    assert row is not None
    assert row.msoa21 is None  # NULLed — no place row for the MSOA
    assert row.ltla24 == "ltla24:E06000004"
    async with engine.connect() as conn:
        stored = (
            await conn.execute(select(Postcode).where(Postcode.postcode == "TS181AB"))
        ).first()
    assert stored is not None
    assert stored.msoa21 is None
    assert stored.lsoa21 == "lsoa21:E01012018"
    assert stored.ltla24 == "ltla24:E06000004"


async def test_upsert_postcode_idempotent() -> None:
    engine = get_engine()
    await _seed_places()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = PostcodesIoAdapter(engine, ttl=timedelta(hours=720), http_client=client)
        await adapter.upsert_postcode("TS18 1AB")
        await adapter.upsert_postcode("TS18 1AB")

    async with engine.connect() as conn:
        n = (await conn.execute(text("SELECT count(*) FROM geography.postcode"))).scalar_one()
    assert n == 1

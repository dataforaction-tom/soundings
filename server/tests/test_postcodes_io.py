from datetime import timedelta

import httpx
import pytest

from soundings.adapters.postcodes_io.adapter import PostcodeLookup, PostcodesIoAdapter
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


SAMPLE_RESPONSE = {
    "status": 200,
    "result": {
        "postcode": "TS18 1AB",
        "codes": {
            "admin_district": "E06000004",  # Stockton-on-Tees (UA -> LTLA)
            "admin_county": "E06000004",
            "admin_ward": "E05014203",
            "parliamentary_constituency_2024": "E14001599",
            "european_electoral_region": "E15000001",
            "country": "E92000001",
            "lsoa": "E01012018",
            "msoa": "E02002565",
            "region": "E12000001",
        },
    },
}


async def test_postcodes_io_lookup_returns_canonical_ids() -> None:
    engine = get_engine()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/postcodes/TS181AB"
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = PostcodesIoAdapter(
            engine, ttl=timedelta(hours=720), http_client=client
        )
        result = await adapter.lookup("TS18 1AB")

    assert result is not None
    assert isinstance(result, PostcodeLookup)
    assert result.postcode == "TS18 1AB"
    assert result.lsoa21 == "lsoa21:E01012018"
    assert result.msoa21 == "msoa21:E02002565"
    assert result.ltla24 == "ltla24:E06000004"
    assert result.utla24 == "utla24:E06000004"
    assert result.ward24 == "ward24:E05014203"
    assert result.westminster_constituency_24 == "westminster_constituency_24:E14001599"
    assert result.region == "region:E12000001"
    assert result.country == "country:E92000001"


async def test_postcodes_io_returns_none_on_404() -> None:
    engine = get_engine()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"status": 404, "error": "Postcode not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = PostcodesIoAdapter(
            engine, ttl=timedelta(hours=720), http_client=client
        )
        result = await adapter.lookup("ZZ99 9ZZ")
    assert result is None

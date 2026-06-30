"""Unit tests for GiveFoodClient (mock transport)."""

import httpx
import pytest

from soundings.adapters.givefood.client import (
    DUMP_URL,
    GiveFoodClient,
    GiveFoodUnavailableError,
)


def _dump_payload() -> list[dict]:
    return [
        {
            "organisation_name": "County Durham",
            "location_name": "Annfield Plain",
            "lat_lng": "54.8588523,-1.7377999",
            "postcode": "DH9 7SY",
            "lsoa": "E01020700",
        },
        {
            "organisation_name": "Solo Org",
            "location_name": "",  # falls back to organisation_name
            "lat_lng": "",  # missing coords -> lat/lng None, lsoa retained
            "postcode": "AB1 2CD",
            "lsoa": "E01099999",
        },
    ]


async def test_fetch_foodbanks_trims_and_parses() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["user_agent"] = request.headers.get("user-agent", "")
        return httpx.Response(200, json=_dump_payload())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GiveFoodClient(http_client=http)
        rows = await client.fetch_foodbanks()

    assert DUMP_URL in str(captured["url"])
    assert "Soundings" in str(captured["user_agent"])
    assert len(rows) == 2
    assert rows[0] == {
        "lat": 54.8588523,
        "lng": -1.7377999,
        "postcode": "DH9 7SY",
        "lsoa": "E01020700",
        "name": "Annfield Plain",
        "org": "County Durham",
    }
    # blank location_name falls back to organisation_name; bad lat_lng -> None
    assert rows[1]["name"] == "Solo Org"
    assert rows[1]["lat"] is None and rows[1]["lng"] is None
    assert rows[1]["lsoa"] == "E01099999"


async def test_fetch_foodbanks_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503, text="unavailable")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GiveFoodClient(http_client=http)
        with pytest.raises(GiveFoodUnavailableError):
            await client.fetch_foodbanks()


async def test_fetch_foodbanks_raises_on_non_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"unexpected": "shape"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GiveFoodClient(http_client=http)
        with pytest.raises(GiveFoodUnavailableError):
            await client.fetch_foodbanks()

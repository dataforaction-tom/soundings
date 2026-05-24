"""Unit tests for FindThatCharityClient (mock transport).

The real API provides:
- `GET /charity/{id}` → charity detail
- `GET /charity/search` → cross-jurisdiction search

No auth required.
"""

import httpx

from soundings.adapters.find_that_charity.client import (
    CharityDetail,
    CharitySearchResult,
    FindThatCharityClient,
)


async def test_get_charity_returns_detail() -> None:
    """`GET /charity/{id}` returns a charity object with detail fields."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/charity/GB-CHC-1145080"
        return httpx.Response(
            200,
            json={
                "id": "GB-CHC-1145080",
                "name": "The Royal British Legion",
                "registered_date": "2011-11-11",
                "postcode": "SW1A 1AA",
                "country": "England",
                "status": "Registered",
                "activities": "The relief of serving and former serving personnel",
                "charitable_objects": "To promote the welfare of all those who serve",
                "url": "https://findthatcharity.uk/charity/1145080",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FindThatCharityClient(http_client=http)
        result = await client.get_charity("GB-CHC-1145080")

    assert result is not None
    assert isinstance(result, CharityDetail)
    assert result.id == "GB-CHC-1145080"
    assert result.name == "The Royal British Legion"
    assert result.country == "England"
    assert result.postcode == "SW1A 1AA"


async def test_get_charity_returns_none_for_404() -> None:
    """A 404 response returns None (charity not found)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not found"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FindThatCharityClient(http_client=http)
        result = await client.get_charity("GB-CHC-999999")

    assert result is None


async def test_search_returns_list_of_results() -> None:
    """`GET /charity/search` returns a list of results."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/charity/search"
        params = dict(request.url.params)
        assert params.get("country") == "Scotland"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "SC005336",
                        "name": "Volunteer Scotland",
                        "postcode": "EH1 1EZ",
                        "country": "Scotland",
                    },
                    {
                        "id": "SC012345",
                        "name": "Scottish Charity Two",
                        "postcode": "G1 1AA",
                        "country": "Scotland",
                    },
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FindThatCharityClient(http_client=http)
        result = await client.search(country="Scotland")

    assert isinstance(result, list)
    assert len(result) == 2
    assert all(isinstance(r, CharitySearchResult) for r in result)
    assert result[0].id == "SC005336"
    assert result[0].country == "Scotland"


async def test_search_accepts_name_postcode_country_and_limit() -> None:
    """Search params are passed through to the API."""

    captured_params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_params.update(dict(request.url.params))
        return httpx.Response(200, json={"results": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FindThatCharityClient(http_client=http)
        await client.search(name="Cancer", postcode="SW1A", country="England", limit=25)

    assert captured_params["name"] == "Cancer"
    assert captured_params["postcode"] == "SW1A"
    assert captured_params["country"] == "England"
    assert captured_params["limit"] == "25"


async def test_get_charity_handles_scottish_id() -> None:
    """Scottish charity IDs (SCxxxxx) are looked up directly."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/charity/SC005336"
        return httpx.Response(
            200,
            json={
                "id": "SC005336",
                "name": "Volunteer Scotland",
                "registered_date": "2001-04-12",
                "postcode": "EH1 1EZ",
                "country": "Scotland",
                "status": "Registered",
                "activities": "Volunteer development",
                "charitable_objects": "To promote volunteering in Scotland",
                "url": "https://findthatcharity.uk/charity/SC005336",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FindThatCharityClient(http_client=http)
        result = await client.get_charity("SC005336")

    assert result is not None
    assert result.id == "SC005336"
    assert result.country == "Scotland"

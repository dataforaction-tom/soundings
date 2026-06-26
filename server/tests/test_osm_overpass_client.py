"""Unit tests for OsmOverpassClient (mock transport).

Mock transport covers the Overpass count-by-tag query and fallback behaviour.
"""

import httpx
import pytest

from soundings.adapters.osm_overpass.client import (
    OVERPASS_FALLBACK,
    OVERPASS_PRIMARY,
    OsmOverpassClient,
    OverpassUnavailableError,
)


def _count_payload(
    total: int, nodes: int = 0, ways: int = 0, relations: int = 0
) -> dict[str, object]:
    return {
        "version": 0.6,
        "generator": "Overpass API",
        "elements": [
            {
                "type": "count",
                "id": 0,
                "tags": {
                    "nodes": str(nodes),
                    "ways": str(ways),
                    "relations": str(relations),
                    "total": str(total),
                },
            }
        ],
    }


async def test_count_by_tag_sends_post_with_overpass_ql_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.content.decode()
        captured["user_agent"] = request.headers.get("user-agent", "")
        return httpx.Response(200, json=_count_payload(15, nodes=12, ways=3))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        count = await client.count_by_tag("amenity", "school", (54.55, -1.34, 54.59, -1.30))

    assert count == 15
    assert captured["method"] == "POST"
    assert OVERPASS_PRIMARY in str(captured["url"])
    # Public Overpass instances 406 a request without a real User-Agent.
    assert "Soundings" in str(captured["user_agent"])
    body = str(captured["body"])
    assert "amenity" in body
    assert "school" in body
    # Bounding box in south,west,north,east order (lat,lng).
    assert "54.55" in body
    assert "-1.34" in body
    assert "54.59" in body
    assert "-1.3" in body
    assert "out count" in body or "out+count" in body


async def test_count_by_tag_sums_nodes_ways_relations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=_count_payload(25, nodes=10, ways=10, relations=5))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        count = await client.count_by_tag("leisure", "park", (50.0, -1.0, 51.0, 1.0))

    assert count == 25


async def test_count_by_tag_returns_zero_when_no_elements() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"version": 0.6, "elements": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        count = await client.count_by_tag("amenity", "hospital", (50.0, -1.0, 51.0, 1.0))

    assert count == 0


async def test_count_by_tag_falls_back_to_main_instance_on_primary_failure() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if OVERPASS_PRIMARY in url:
            return httpx.Response(503, text="Overpass server overloaded")
        return httpx.Response(200, json=_count_payload(7, nodes=5, ways=2))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        count = await client.count_by_tag("amenity", "library", (54.0, -1.0, 55.0, 0.0))

    assert count == 7
    assert any(OVERPASS_PRIMARY in u for u in calls)
    assert any(OVERPASS_FALLBACK in u for u in calls)


async def test_count_by_tag_raises_when_all_endpoints_fail() -> None:
    # Regression: a transport failure on every endpoint must NOT be reported
    # as a count of 0. A real zero (endpoint responded, no matching elements)
    # is indistinguishable downstream from "we never reached Overpass" — and
    # the adapter would cache the bogus 0 for 30 days. Surface it as an error
    # so it becomes a caveat instead.
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503, text="Overpass server overloaded")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        with pytest.raises(OverpassUnavailableError):
            await client.count_by_tag("amenity", "school", (54.0, -1.0, 55.0, 0.0))


async def test_count_by_tag_raises_when_response_is_not_json() -> None:
    # The public Overpass mirror often returns an HTML rate-limit page with a
    # 200 status. response.json() raises json.JSONDecodeError, which is not an
    # httpx.HTTPError — it used to escape the except clause uncaught.
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="<html>too many requests</html>")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        with pytest.raises(OverpassUnavailableError):
            await client.count_by_tag("amenity", "school", (54.0, -1.0, 55.0, 0.0))


async def test_count_by_tag_returns_zero_on_unexpected_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"unexpected": "shape"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        count = await client.count_by_tag("amenity", "pharmacy", (50.0, -1.0, 51.0, 1.0))

    assert count == 0


def _locations_payload() -> dict[str, object]:
    # A node (direct lat/lon), a way (center), and one unnamed node.
    return {
        "version": 0.6,
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 54.77,
                "lon": -1.57,
                "tags": {"name": "Durham Foodbank"},
            },
            {
                "type": "way",
                "id": 2,
                "center": {"lat": 54.70, "lon": -1.50},
                "tags": {"name": "St X Pantry"},
            },
            {"type": "node", "id": 3, "lat": 54.60, "lon": -1.40, "tags": {}},
        ],
    }


async def test_locations_by_tag_parses_nodes_and_centers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=_locations_payload())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        pts = await client.locations_by_tag("amenity", "food_bank", (54.5, -1.7, 54.9, -1.3))

    assert len(pts) == 3
    assert pts[0] == {"lat": 54.77, "lng": -1.57, "name": "Durham Foodbank"}
    assert pts[1]["lat"] == 54.70 and pts[1]["lng"] == -1.50  # way centroid
    assert pts[2]["name"] is None  # unnamed


async def test_locations_by_tag_empty_elements_returns_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"version": 0.6, "elements": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        pts = await client.locations_by_tag("amenity", "school", (54.5, -1.7, 54.9, -1.3))
    assert pts == []  # valid "none here", not an error


async def test_locations_by_tag_raises_when_all_endpoints_fail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503, text="overloaded")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        with pytest.raises(OverpassUnavailableError):
            await client.locations_by_tag("amenity", "school", (54.5, -1.7, 54.9, -1.3))

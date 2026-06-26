"""Unit tests for OsmOverpassClient (mock transport).

Mock transport covers the Overpass count-by-tag query and fallback behaviour.
"""

import httpx

from soundings.adapters.osm_overpass.client import (
    OVERPASS_FALLBACK,
    OVERPASS_PRIMARY,
    OsmOverpassClient,
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
        return httpx.Response(200, json=_count_payload(15, nodes=12, ways=3))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        count = await client.count_by_tag("amenity", "school", (54.55, -1.34, 54.59, -1.30))

    assert count == 15
    assert captured["method"] == "POST"
    assert OVERPASS_PRIMARY in str(captured["url"])
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


async def test_count_by_tag_returns_zero_on_unexpected_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"unexpected": "shape"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        count = await client.count_by_tag("amenity", "pharmacy", (50.0, -1.0, 51.0, 1.0))

    assert count == 0

"""Unit tests for OpenAqClient (mock transport).

Mock transport covers /v3/locations and /v3/sensors/{id}/measurements.
"""

import httpx

from soundings.adapters.openaq.client import OpenAqClient


def _locations_payload() -> dict[str, object]:
    return {
        "meta": {
            "name": "openaq",
            "website": "api.openaq.org",
            "page": 1,
            "limit": 100,
            "found": 1,
        },
        "results": [
            {
                "id": 12345,
                "name": "Middlesbrough AURN",
                "coordinates": {"latitude": 54.576, "longitude": -1.318},
                "sensors": [
                    {"id": 9001, "parameter": {"name": "pm25", "units": "µg/m³"}},
                    {"id": 9002, "parameter": {"name": "pm10", "units": "µg/m³"}},
                ],
            }
        ],
    }


def _measurements_payload(value: float) -> dict[str, object]:
    return {
        "meta": {"name": "openaq", "website": "api.openaq.org", "page": 1, "limit": 1, "found": 1},
        "results": [
            {
                "value": value,
                "parameter": {"name": "pm25", "units": "µg/m³"},
                "period": {"interval": "1h", "label": "1 hour"},
                "datetime": {
                    "utc": "2026-06-26T10:00:00+00:00",
                    "local": "2026-06-26T11:00:00+01:00",
                },
            }
        ],
    }


async def test_get_nearby_locations_sends_coordinates_and_radius() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        return httpx.Response(200, json=_locations_payload())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OpenAqClient(http_client=http)
        locations = await client.get_nearby_locations(54.57, -1.32, radius_meters=20000)

    url = str(captured["url"])
    assert url.startswith("https://api.openaq.org/v3/locations")
    assert captured["method"] == "GET"
    assert "coordinates=54.57" in url and "-1.32" in url
    assert "radius_meters=20000" in url
    assert len(locations) == 1
    assert locations[0]["id"] == 12345
    assert "sensors" in locations[0]


async def test_get_nearby_locations_returns_empty_on_no_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"meta": {"found": 0}, "results": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OpenAqClient(http_client=http)
        locations = await client.get_nearby_locations(0.0, 0.0)
    assert locations == []


async def test_get_latest_measurement_returns_value() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_measurements_payload(12.5))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OpenAqClient(http_client=http)
        value = await client.get_latest_measurement(9001)

    url = str(captured["url"])
    assert "/v3/sensors/9001/measurements" in url
    assert "limit=1" in url
    assert "order_by=datetime" in url
    assert "sort=desc" in url
    assert value == 12.5


async def test_get_latest_measurement_returns_none_on_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"meta": {"found": 0}, "results": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OpenAqClient(http_client=http)
        value = await client.get_latest_measurement(9999)
    assert value is None


async def test_get_latest_measurement_handles_unexpected_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"unexpected": "shape"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OpenAqClient(http_client=http)
        value = await client.get_latest_measurement(1)
    assert value is None

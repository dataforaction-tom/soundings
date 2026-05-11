import httpx

from soundings.adapters.ohid_fingertips.client import (
    FINGERTIPS_BASE,
    FingertipsClient,
)


async def test_client_hits_all_data_by_indicator_id_with_query_params() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json=[
                {"AreaCode": "E06000004", "Value": 81.2, "Year": 2022},
                {"AreaCode": "E06000005", "Value": 79.8, "Year": 2022},
            ],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        rows = await client.get_indicator_data(
            indicator_id=90366, child_area_type_id=102, parent_area_type_id=15
        )

    assert FINGERTIPS_BASE in captured["url"]
    assert "indicator_id=90366" in captured["url"]
    assert "child_area_type_id=102" in captured["url"]
    assert "parent_area_type_id=15" in captured["url"]
    assert len(rows) == 2
    assert rows[0]["AreaCode"] == "E06000004"


async def test_client_returns_empty_list_when_payload_isnt_a_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"error": "unexpected"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        rows = await client.get_indicator_data(indicator_id=1, child_area_type_id=102)
    assert rows == []


async def test_client_omits_parent_area_type_id_when_not_supplied() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        await client.get_indicator_data(indicator_id=1, child_area_type_id=102)
    assert "parent_area_type_id" not in captured["url"]

import httpx

from soundings.adapters.ohid_fingertips.client import FINGERTIPS_BASE, FingertipsClient


async def test_client_hits_latest_data_endpoint_with_query_params() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json=[
                {
                    "Grouping": [{"IndicatorId": 90366}],
                    "Sex": {"Id": 2, "Name": "Female"},
                    "Age": {"Id": 1, "Name": "All ages"},
                    "Data": [
                        {
                            "AreaCode": "E06000004",
                            "IndicatorId": 90366,
                            "Val": 81.2,
                            "Year": 2023,
                            "YearRange": 3,
                        }
                    ],
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        records = await client.get_group_data(
            profile_id=19,
            group_id=1000049,
            area_type_id=501,
            parent_area_code="E92000001",
        )

    assert FINGERTIPS_BASE in captured["url"]
    assert "latest_data/all_indicators_in_profile_group_for_child_areas" in captured["url"]
    assert "profile_id=19" in captured["url"]
    assert "group_id=1000049" in captured["url"]
    assert "area_type_id=501" in captured["url"]
    assert "parent_area_code=E92000001" in captured["url"]
    assert len(records) == 1


async def test_client_returns_empty_list_when_payload_isnt_a_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"error": "unexpected"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = FingertipsClient(http_client=http)
        records = await client.get_group_data(profile_id=19, group_id=1000049, area_type_id=501)
    assert records == []

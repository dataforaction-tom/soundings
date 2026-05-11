import httpx
import pytest

from soundings.adapters.nomis.client import NomisClient


async def test_nomis_client_builds_correct_url() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "obs": [
                    {
                        "obs_value": {"value": 100},
                        "geography": {"geogcode": "E01000001"},
                        "time": {"description": "2021"},
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = NomisClient(http_client=http)
        result = await client.get_observations(
            dataset_id="NM_2010_1",
            geography="E01000001",
            measures="20100",
            time="latest",
        )
    assert "/dataset/NM_2010_1.data.json" in captured["url"]
    assert "geography=E01000001" in captured["url"]
    assert result["obs"][0]["obs_value"]["value"] == 100


async def test_nomis_client_attaches_api_key_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOMIS_API_KEY", "secret-key")
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["uid_param"] = request.url.params.get("uid", "")
        return httpx.Response(200, json={"obs": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = NomisClient(http_client=http)
        await client.get_observations(dataset_id="NM_2010_1", geography="E01000001")
    assert captured["uid_param"] == "secret-key"

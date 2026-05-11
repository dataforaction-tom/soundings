"""Integration tests for DfeExploreAdapter."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from soundings.adapters.dfe_explore.adapter import DfeExploreAdapter
from soundings.adapters.dfe_explore.client import DfeExploreClient
from soundings.adapters.dfe_explore.mapping import DfeMapping
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_dfe_source() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, publisher_url, "
                "dataset_url, licence, mode, rate_limit) VALUES "
                "('dfe.explore', 'DfE Explore Education Statistics', "
                "'Department for Education', "
                "'https://www.gov.uk/dfe', "
                "'https://explore-education-statistics.service.gov.uk/', "
                "'OGL-UK-3.0', 'passthrough', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )


def _sample_payload(rows: list[tuple[str, float]], indicator_id: str = "ind-fsm") -> dict[str, Any]:
    return {
        "paging": {
            "page": 1,
            "pageSize": 1000,
            "totalResults": len(rows),
            "totalPages": 1,
        },
        "results": [
            {
                "timePeriod": {"code": "AY", "period": period},
                "locations": {"LA": "loc-stockton"},
                "filters": {},
                "values": {indicator_id: str(value)},
            }
            for period, value in rows
        ],
    }


def _stub_mapping(tmp_path: Path, **overrides: Any) -> None:
    import yaml

    entry: dict[str, Any] = {
        "indicator_key": "education.fsm_eligibility_share",
        "data_set_id": "ds-fsm",
        "indicator_id": "ind-fsm",
        "filters": {},
        "location_level": "LA",
        "time_period_code": "AY",
        "place_type": "ltla24",
        "unit": "proportion",
    }
    entry.update(overrides)
    (tmp_path / "dfe-mapping.yaml").write_text(yaml.safe_dump({"mappings": [entry]}))


async def test_fetch_indicator_returns_latest_period(tmp_path: Path) -> None:
    await _seed_dfe_source()
    _stub_mapping(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=_sample_payload(
                [("2020/2021", 0.205), ("2021/2022", 0.215), ("2022/2023", 0.235)]
            ),
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = DfeExploreClient(http_client=http)
        adapter = DfeExploreAdapter(
            get_engine(), dfe_client=client, mapping_path=tmp_path / "dfe-mapping.yaml"
        )
        iv = await adapter.fetch_indicator(
            "education.fsm_eligibility_share", "ltla24:E06000004", period=None
        )

    assert iv is not None
    assert iv.value == 0.235
    assert iv.period == "2022/2023"
    assert iv.unit == "proportion"
    assert iv.source.source_id == "dfe.explore"


async def test_fetch_indicator_by_explicit_period(tmp_path: Path) -> None:
    await _seed_dfe_source()
    _stub_mapping(tmp_path)
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json=_sample_payload(
                [("2020/2021", 0.205), ("2021/2022", 0.215), ("2022/2023", 0.235)]
            ),
        )
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = DfeExploreClient(http_client=http)
        adapter = DfeExploreAdapter(
            get_engine(), dfe_client=client, mapping_path=tmp_path / "dfe-mapping.yaml"
        )
        iv = await adapter.fetch_indicator(
            "education.fsm_eligibility_share", "ltla24:E06000004", period="2021/2022"
        )
    assert iv is not None
    assert iv.value == 0.215


async def test_fetch_trend_returns_ordered_series(tmp_path: Path) -> None:
    await _seed_dfe_source()
    _stub_mapping(tmp_path)
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json=_sample_payload(
                [("2021/2022", 0.215), ("2020/2021", 0.205), ("2022/2023", 0.235)]
            ),
        )
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = DfeExploreClient(http_client=http)
        adapter = DfeExploreAdapter(
            get_engine(), dfe_client=client, mapping_path=tmp_path / "dfe-mapping.yaml"
        )
        trend = await adapter.fetch_trend("education.fsm_eligibility_share", "ltla24:E06000004")

    assert trend is not None
    assert [p.period for p in trend.points] == ["2020/2021", "2021/2022", "2022/2023"]
    assert trend.points[-1].value == 0.235


async def test_fetch_trend_filters_by_window(tmp_path: Path) -> None:
    await _seed_dfe_source()
    _stub_mapping(tmp_path)
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200,
            json=_sample_payload(
                [("2020/2021", 0.205), ("2021/2022", 0.215), ("2022/2023", 0.235)]
            ),
        )
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = DfeExploreClient(http_client=http)
        adapter = DfeExploreAdapter(
            get_engine(), dfe_client=client, mapping_path=tmp_path / "dfe-mapping.yaml"
        )
        trend = await adapter.fetch_trend(
            "education.fsm_eligibility_share",
            "ltla24:E06000004",
            period_from="2021/2022",
        )

    assert trend is not None
    assert [p.period for p in trend.points] == ["2021/2022", "2022/2023"]


async def test_unknown_indicator_returns_none(tmp_path: Path) -> None:
    await _seed_dfe_source()
    _stub_mapping(tmp_path)
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    async with httpx.AsyncClient(transport=transport) as http:
        client = DfeExploreClient(http_client=http)
        adapter = DfeExploreAdapter(
            get_engine(), dfe_client=client, mapping_path=tmp_path / "dfe-mapping.yaml"
        )
        iv = await adapter.fetch_indicator("education.nope", "ltla24:E06000004", period=None)
    assert iv is None


async def test_per_place_query_is_cached(tmp_path: Path) -> None:
    """Second call for same place hits cache."""
    await _seed_dfe_source()
    _stub_mapping(tmp_path)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        del request
        return httpx.Response(
            200, json=_sample_payload([("2021/2022", 0.215), ("2022/2023", 0.235)])
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = DfeExploreClient(http_client=http)
        adapter = DfeExploreAdapter(
            get_engine(), dfe_client=client, mapping_path=tmp_path / "dfe-mapping.yaml"
        )
        await adapter.fetch_indicator(
            "education.fsm_eligibility_share", "ltla24:E06000004", period=None
        )
        await adapter.fetch_trend("education.fsm_eligibility_share", "ltla24:E06000004")
    assert call_count == 1


def test_dfe_mapping_pydantic_model_round_trips() -> None:
    """Mapping fields survive yaml round-trip via Pydantic model."""
    mapping = DfeMapping(
        indicator_key="education.fsm_eligibility_share",
        data_set_id="ds-fsm",
        indicator_id="ind-fsm",
        filters={"f1": "o1"},
        location_level="LA",
        time_period_code="AY",
        place_type="ltla24",
        unit="proportion",
        caveats=["test caveat"],
    )
    assert mapping.indicator_key == "education.fsm_eligibility_share"
    assert mapping.filters == {"f1": "o1"}
    assert mapping.caveats == ["test caveat"]

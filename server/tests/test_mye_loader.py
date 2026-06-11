import httpx
import pytest
from sqlalchemy import select, text

from soundings.adapters.nomis.client import NomisClient
from soundings.adapters.ons_mid_year_estimates.loader import OnsMidYearEstimatesLoader
from soundings.db.engine import get_engine
from soundings.db.models.data import IndicatorValue, TrendPoint

pytestmark = pytest.mark.integration


NOMIS_RESPONSE_BY_GEO = {
    "E06000004": [
        {
            "obs_value": {"value": 200000},
            "geography": {"geogcode": "E06000004"},
            "time": {"description": "2024"},
        },
    ],
    "E12000001": [
        {
            "obs_value": {"value": 2700000},
            "geography": {"geogcode": "E12000001"},
            "time": {"description": "2024"},
        },
    ],
}


async def _seed_environment() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.loader_run"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        for place_id, place_type, code, name in [
            ("ltla24:E06000004", "ltla24", "E06000004", "Stockton-on-Tees"),
            ("region:E12000001", "region", "E12000001", "North East"),
        ]:
            await conn.execute(
                text("INSERT INTO geography.place (id, type, code, name) VALUES (:id, :t, :c, :n)"),
                {"id": place_id, "t": place_type, "c": code, "n": name},
            )


async def test_mye_loader_writes_indicator_value_rows() -> None:
    engine = get_engine()
    await _seed_environment()

    def handler(request: httpx.Request) -> httpx.Response:
        geo = request.url.params.get("geography", "")
        # Test exercises only one indicator at a time, so we infer the geo
        # code from the query and return its sample.
        for code, obs in NOMIS_RESPONSE_BY_GEO.items():
            if code in geo:
                return httpx.Response(200, json={"obs": obs})
        return httpx.Response(200, json={"obs": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        nomis = NomisClient(http_client=http)
        loader = OnsMidYearEstimatesLoader(
            engine,
            nomis_client=nomis,
            indicator_keys=["population.total"],  # restrict scope for test
        )
        result = await loader.load()

    assert result.rows_written >= 2

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(IndicatorValue.place_id, IndicatorValue.value, IndicatorValue.period)
                .where(IndicatorValue.indicator_key == "population.total")
                .order_by(IndicatorValue.place_id)
            )
        ).all()
    by_place = {r.place_id: float(r.value) for r in rows}
    assert by_place["ltla24:E06000004"] == 200000
    assert by_place["region:E12000001"] == 2700000


# Multi-year fixture: Nomis returns the full series when the loader asks for
# a year range instead of `time=latest`. The handler keys off the absence of
# `time=latest` to switch shape.
NOMIS_TREND_BY_GEO = {
    "E06000004": [
        {
            "obs_value": {"value": 195000},
            "geography": {"geogcode": "E06000004"},
            "time": {"description": "2022"},
        },
        {
            "obs_value": {"value": 197500},
            "geography": {"geogcode": "E06000004"},
            "time": {"description": "2023"},
        },
        {
            "obs_value": {"value": 200000},
            "geography": {"geogcode": "E06000004"},
            "time": {"description": "2024"},
        },
    ],
}


async def test_mye_loader_writes_trend_points() -> None:
    engine = get_engine()
    await _seed_environment()

    def handler(request: httpx.Request) -> httpx.Response:
        geo = request.url.params.get("geography", "")
        for code, obs in NOMIS_TREND_BY_GEO.items():
            if code in geo:
                return httpx.Response(200, json={"obs": obs})
        return httpx.Response(200, json={"obs": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        nomis = NomisClient(http_client=http)
        loader = OnsMidYearEstimatesLoader(
            engine,
            nomis_client=nomis,
            indicator_keys=["population.total"],
            place_filter=["ltla24:E06000004"],
        )
        await loader.load()

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(TrendPoint.period, TrendPoint.value)
                .where(TrendPoint.indicator_key == "population.total")
                .where(TrendPoint.place_id == "ltla24:E06000004")
                .order_by(TrendPoint.period)
            )
        ).all()
    assert [(r.period, float(r.value)) for r in rows] == [
        ("2022", 195000.0),
        ("2023", 197500.0),
        ("2024", 200000.0),
    ]

import httpx
import pytest
from sqlalchemy import select, text

from soundings.adapters.nomis.client import NomisClient
from soundings.adapters.ons_census2021.loader import OnsCensus2021Loader
from soundings.db.engine import get_engine
from soundings.db.models.data import IndicatorValue

pytestmark = pytest.mark.integration


async def _seed_environment() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:E06000004', 'ltla24', 'E06000004', 'Stockton-on-Tees')"
            )
        )


async def test_census_loader_writes_indicator_value_rows() -> None:
    engine = get_engine()
    await _seed_environment()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "obs": [
                    {
                        "obs_value": {"value": 18.0},
                        "geography": {"geogcode": "E06000004"},
                        "time": {"description": "2021"},
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        nomis = NomisClient(http_client=http)
        loader = OnsCensus2021Loader(
            engine,
            nomis_client=nomis,
            indicator_keys=["population.households.lone_parent_share"],
        )
        result = await loader.load()

    assert result.rows_written >= 1

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(IndicatorValue.place_id, IndicatorValue.value, IndicatorValue.period).where(
                    IndicatorValue.indicator_key == "population.households.lone_parent_share"
                )
            )
        ).all()
    assert any(r.place_id == "ltla24:E06000004" and float(r.value) == 0.18 for r in rows)


async def test_census_loader_skips_scottish_geographies() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES "
                "('ltla24:S12000033', 'ltla24', 'S12000033', 'Aberdeen City'), "
                "('ltla24:E06000004', 'ltla24', 'E06000004', 'Stockton-on-Tees')"
            )
        )

    upstream_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        upstream_calls.append(request.url.params.get("geography", ""))
        return httpx.Response(
            200,
            json={
                "obs": [
                    {
                        "obs_value": {"value": 10.0},
                        "geography": {"geogcode": "E06000004"},
                        "time": {"description": "2021"},
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        nomis = NomisClient(http_client=http)
        loader = OnsCensus2021Loader(
            engine,
            nomis_client=nomis,
            indicator_keys=["population.households.lone_parent_share"],
        )
        await loader.load()

    # Scottish code S12000033 must never be queried against Nomis.
    assert all("S12000033" not in g for g in upstream_calls)
    # Census caveat is stamped on every row.
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT caveats FROM data.indicator_value "
                    "WHERE indicator_key = 'population.households.lone_parent_share'"
                )
            )
        ).all()
    assert all(any("England and Wales only" in c for c in (row.caveats or [])) for row in rows)

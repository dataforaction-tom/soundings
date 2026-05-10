import httpx
import pytest
from sqlalchemy import select, text

from soundings.adapters.ons_geography.hierarchy_loader import (
    LookupChain,
    OnsGeographyHierarchyLoader,
)
from soundings.db.engine import get_engine
from soundings.db.models.geography import Place, PlaceHierarchy

pytestmark = pytest.mark.integration


async def _seed_places(ids: dict[str, str]) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place"))
        for place_id, name in ids.items():
            type_, code = place_id.split(":", 1)
            await conn.execute(
                Place.__table__.insert().values(id=place_id, type=type_, code=code, name=name)
            )


async def test_hierarchy_loader_expands_transitive_edges() -> None:
    engine = get_engine()
    await _seed_places(
        {
            "lsoa21:E01000001": "City of London 001A",
            "lsoa21:E01000002": "City of London 001B",
            "msoa21:E02000001": "City of London 001",
            "msoa21:E02000002": "City of London 002",
            "ltla24:E09000001": "City of London",
        }
    )

    rows = [
        {
            "LSOA21CD": "E01000001",
            "MSOA21CD": "E02000001",
            "LAD24CD": "E09000001",
        },
        {
            "LSOA21CD": "E01000002",
            "MSOA21CD": "E02000002",
            "LAD24CD": "E09000001",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"features": [{"attributes": r} for r in rows]})

    transport = httpx.MockTransport(handler)
    chain = LookupChain(
        url="https://example.invalid/lookup/FeatureServer/0",
        levels=[
            ("lsoa21", "LSOA21CD"),
            ("msoa21", "MSOA21CD"),
            ("ltla24", "LAD24CD"),
        ],
    )

    async with httpx.AsyncClient(transport=transport) as client:
        loader = OnsGeographyHierarchyLoader(engine, http_client=client, chains=[chain])
        result = await loader.load()

    # 2 LSOAs * (MSOA + LTLA edges) + 2 MSOAs * LTLA edge = 6 distinct edges
    assert result.rows_written == 6

    async with engine.connect() as conn:
        edges = {
            (r.child_id, r.parent_id)
            for r in (
                await conn.execute(select(PlaceHierarchy.child_id, PlaceHierarchy.parent_id))
            ).all()
        }
    assert ("lsoa21:E01000001", "msoa21:E02000001") in edges
    assert ("lsoa21:E01000001", "ltla24:E09000001") in edges
    assert ("msoa21:E02000001", "ltla24:E09000001") in edges
    assert ("lsoa21:E01000002", "ltla24:E09000001") in edges


async def test_hierarchy_loader_is_idempotent() -> None:
    engine = get_engine()
    await _seed_places(
        {
            "lsoa21:E01000001": "x",
            "msoa21:E02000001": "y",
            "ltla24:E09000001": "z",
        }
    )

    rows = [{"LSOA21CD": "E01000001", "MSOA21CD": "E02000001", "LAD24CD": "E09000001"}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"features": [{"attributes": r} for r in rows]})

    transport = httpx.MockTransport(handler)
    chain = LookupChain(
        url="https://example.invalid/lookup/FeatureServer/0",
        levels=[("lsoa21", "LSOA21CD"), ("msoa21", "MSOA21CD"), ("ltla24", "LAD24CD")],
    )

    async with httpx.AsyncClient(transport=transport) as client:
        loader = OnsGeographyHierarchyLoader(engine, http_client=client, chains=[chain])
        await loader.load()
        await loader.load()

    async with engine.connect() as conn:
        n_edges = (
            await conn.execute(text("SELECT count(*) FROM geography.place_hierarchy"))
        ).scalar_one()
    assert n_edges == 3

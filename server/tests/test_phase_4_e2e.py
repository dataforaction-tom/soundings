"""Phase 4 e2e — find_organisations_in_place across CC + FTC paths.

Per Phase 4 plan Task 28. Covers the mixed-mode dispatch end-to-end:

- England (`ltla24:E06000004`, Stockton-on-Tees) → SQL SELECT from
  `data.organisation` (CC loader path).
- Scotland (`ltla24:S12000033`, Aberdeen City) → FTC passthrough.

Seeds the catalogue + geography + a handful of CC organisations
directly; patches `FindThatCharityClient.search` to return canned
results for the Scotland leg so the test doesn't hit the FTC API.
Asserts the right adapter served each request and the response shape
matches the contract.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from soundings.adapters.find_that_charity.client import CharitySearchResult
from soundings.app import app
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


STOCKTON = "ltla24:E06000004"
ABERDEEN = "ltla24:S12000033"


@pytest_asyncio.fixture(autouse=True)
async def _phase_4_e2e_cleanup() -> AsyncIterator[None]:
    """Wipe everything this test seeds so it can run repeatedly and
    so a partial failure doesn't poison the next test."""
    yield
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.organisation_operates_in"))
        await conn.execute(text("DELETE FROM data.organisation"))
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))


async def _seed() -> None:
    """Catalogue rows + the two test places + CC orgs registered in Stockton."""
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        for sid, label, publisher, mode in [
            ("charity_commission", "Charity Commission", "CC", "loader"),
            ("threesixtygiving", "360Giving Datastore", "360Giving", "passthrough"),
            ("find_that_charity", "Find That Charity", "FTC", "passthrough"),
        ]:
            await conn.execute(
                text(
                    "INSERT INTO catalogue.source (id, label, publisher, licence, mode, rate_limit) "
                    "VALUES (:sid, :label, :pub, 'open', :mode, '{}'::jsonb) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"sid": sid, "label": label, "pub": publisher, "mode": mode},
            )

        for place_id, code, name in [
            (STOCKTON, "E06000004", "Stockton-on-Tees"),
            (ABERDEEN, "S12000033", "Aberdeen City"),
        ]:
            await conn.execute(
                text(
                    "INSERT INTO geography.place (id, type, code, name) "
                    "VALUES (:id, 'ltla24', :code, :name) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": place_id, "code": code, "name": name},
            )

        for cc_id, name in [
            ("charity_commission:1001", "Stockton Community Trust"),
            ("charity_commission:1002", "Tees Valley Music Centre"),
        ]:
            await conn.execute(
                text(
                    "INSERT INTO data.organisation "
                    "(id, name, source_id, registered_address_place_id, "
                    " classification, retrieved_at, raw) "
                    "VALUES (:id, :name, 'charity_commission', :pid, "
                    "        ARRAY[]::varchar[], :ret, '{}'::jsonb) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"id": cc_id, "name": name, "pid": STOCKTON, "ret": now},
            )


def _ftc_aberdeen_results() -> list[CharitySearchResult]:
    return [
        CharitySearchResult(
            id="SC005336", name="Glasgow City Mission", postcode=None, country="Scotland"
        ),
        CharitySearchResult(
            id="SC012345",
            name="Aberdeen Community Trust",
            postcode="AB10 1XL",
            country="Scotland",
        ),
    ]


async def _post(client: AsyncClient, place_id: str) -> dict:
    response = await client.post(
        "/v1/tools/find_organisations_in_place",
        json={"place_id": place_id, "limit": 10},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_find_organisations_dispatches_cc_for_england_ftc_for_scotland() -> None:
    """One test, two legs — proves the dispatch is wired correctly and
    each leg returns rows with the expected source.source_id."""
    await _seed()

    with patch(
        "soundings.adapters.find_that_charity.client.FindThatCharityClient.search",
        new=AsyncMock(return_value=_ftc_aberdeen_results()),
    ):
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                england = await _post(ac, STOCKTON)
                scotland = await _post(ac, ABERDEEN)

    # --- England leg: CC loader served from data.organisation ---
    assert england["partial"] is False
    england_orgs = england["organisations"]
    assert len(england_orgs) == 2
    assert {o["name"] for o in england_orgs} == {
        "Stockton Community Trust",
        "Tees Valley Music Centre",
    }
    assert all(o["source"]["source_id"] == "charity_commission" for o in england_orgs)
    assert all(o["source"]["cache_status"] == "cached" for o in england_orgs)
    assert all(o["registered_address_place_id"] == STOCKTON for o in england_orgs)

    # --- Scotland leg: FTC passthrough served from the mocked search ---
    scotland_orgs = scotland["organisations"]
    assert len(scotland_orgs) == 2
    assert {o["name"] for o in scotland_orgs} == {
        "Glasgow City Mission",
        "Aberdeen Community Trust",
    }
    assert all(o["source"]["source_id"] == "find_that_charity" for o in scotland_orgs)
    assert all(o["source"]["cache_status"] == "live" for o in scotland_orgs)

    # Response-shape sanity (mirrors FindOrganisationsInPlaceOutput).
    for response in (england, scotland):
        assert set(response.keys()) >= {"organisations", "sources", "caveats", "partial"}
        for org in response["organisations"]:
            assert set(org.keys()) >= {
                "id",
                "name",
                "classification",
                "recent_grants",
                "source",
            }

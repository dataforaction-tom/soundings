"""Phase 3 server-side e2e — compare + trend through the real registry.

Per Phase 3 plan Task 42. Seeds three LTLAs with population.total values
plus a Fingertips life-expectancy trend (via cache.source_cache so the
Fingertips passthrough adapter serves from cache, no network needed),
then exercises:

- POST /v1/tools/compare_places — three places, indicator population.total,
  basis=percentile → ranked response (rank 1 = highest, percentile 0/50/100).
- POST /v1/tools/get_trend — one place, indicator health.life_expectancy.female
  → ordered three-point series with the right unit + source.

Both calls round-trip through the FastAPI lifespan-registered
AdapterRegistry — exactly what a real client sees.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from soundings.app import app
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_phase_3_e2e() -> AsyncIterator[None]:
    yield
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM cache.source_cache"))


PLACES = [
    ("E06000001", "Hartlepool", 92_000.0),
    ("E06000004", "Stockton-on-Tees", 196_000.0),
    ("E06000005", "Darlington", 107_000.0),
]


async def _seed_three_ltlas() -> None:
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        for code, name, pop in PLACES:
            await conn.execute(
                text(
                    "INSERT INTO geography.place (id, type, code, name) "
                    "VALUES (:id, 'ltla24', :code, :name)"
                ),
                {"id": f"ltla24:{code}", "code": code, "name": name},
            )
            await conn.execute(
                text(
                    "INSERT INTO data.indicator_value "
                    "(place_id, indicator_key, period, value, source_id, "
                    "retrieved_at, caveats) VALUES "
                    "(:pid, 'population.total', '2024', :val, "
                    "'ons.mid_year_estimates', :ret, '[]'::jsonb)"
                ),
                {"pid": f"ltla24:{code}", "val": pop, "ret": now},
            )


async def _seed_fingertips_le_cache(stockton_code: str) -> None:
    """Inject a Fingertips group-data response into cache.source_cache so
    the OhidFingertipsAdapter resolves health.life_expectancy.female from
    the cache. Matches the cache_key shape in
    `OhidFingertipsAdapter._fetch_group_page` and the record shape Fingertips
    actually publishes (Sex / Age / Grouping / Data)."""
    # Mapping defaults from catalogue/fingertips-mapping.yaml for
    # health.life_expectancy.female (profile/group/area/sex/age IDs match).
    profile_id = 19
    group_id = 1000049
    area_type_id = 501
    parent_area_code = "E92000001"
    sex_id = 2  # Female
    age_id = 1  # All ages at birth
    indicator_id = 90366
    cache_key = f"fingertips:group:{profile_id}:{group_id}:{area_type_id}:{parent_area_code}"

    records = [
        {
            "IID": indicator_id,
            "Sex": {"Id": sex_id, "Name": "Female"},
            "Age": {"Id": age_id, "Name": "All ages"},
            "Grouping": [{"IndicatorId": indicator_id}],
            "Data": [
                {
                    "IndicatorId": indicator_id,
                    "AreaCode": stockton_code,
                    "Year": 2021,
                    "YearRange": 3,
                    "Val": 80.6,
                },
                {
                    "IndicatorId": indicator_id,
                    "AreaCode": stockton_code,
                    "Year": 2022,
                    "YearRange": 3,
                    "Val": 80.9,
                },
                {
                    "IndicatorId": indicator_id,
                    "AreaCode": stockton_code,
                    "Year": 2023,
                    "YearRange": 3,
                    "Val": 81.2,
                },
            ],
        },
    ]

    engine = get_engine()
    now = datetime.now(tz=UTC)
    expires = now + timedelta(hours=24)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO cache.source_cache "
                "(source_id, cache_key, payload, retrieved_at, expires_at) "
                "VALUES ('ohid.fingertips', :ck, CAST(:payload AS jsonb), :ret, :exp) "
                "ON CONFLICT (source_id, cache_key) DO UPDATE SET "
                "payload = EXCLUDED.payload, "
                "retrieved_at = EXCLUDED.retrieved_at, "
                "expires_at = EXCLUDED.expires_at"
            ),
            {
                "ck": cache_key,
                "payload": _json_dumps(records),
                "ret": now,
                "exp": expires,
            },
        )


def _json_dumps(value: object) -> str:
    import json

    return json.dumps(value)


async def test_compare_places_ranks_three_ltlas_by_population() -> None:
    await _seed_three_ltlas()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/v1/tools/compare_places",
                json={
                    "place_ids": [f"ltla24:{p[0]}" for p in PLACES],
                    "indicators": ["population.total"],
                    "comparison_basis": "percentile",
                },
            )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["results"]) == 1
    comparison = body["results"][0]
    assert comparison["indicator"] == "population.total"
    by_pid = {v["place_id"]: v for v in comparison["values"]}
    # Stockton (196k) > Darlington (107k) > Hartlepool (92k)
    assert by_pid["ltla24:E06000004"]["rank"] == 1
    assert by_pid["ltla24:E06000004"]["percentile"] == pytest.approx(100.0)
    assert by_pid["ltla24:E06000005"]["rank"] == 2
    assert by_pid["ltla24:E06000005"]["percentile"] == pytest.approx(50.0)
    assert by_pid["ltla24:E06000001"]["rank"] == 3
    assert by_pid["ltla24:E06000001"]["percentile"] == pytest.approx(0.0)


async def test_get_trend_via_fingertips_passthrough_serves_from_cache() -> None:
    await _seed_three_ltlas()
    await _seed_fingertips_le_cache("E06000004")

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/v1/tools/get_trend",
                json={
                    "place_id": "ltla24:E06000004",
                    "indicator": "health.life_expectancy.female",
                },
            )

    assert response.status_code == 200, response.text
    body = response.json()
    trend = body["trend"]
    assert trend is not None, f"no trend returned: {body}"
    assert trend["unit"] == "years"
    assert trend["source"]["source_id"] == "ohid.fingertips"
    assert len(trend["points"]) == 3
    # Fingertips period strings: single-year YYYY, multi-year "YYYY - YY" range.
    periods = [p["period"] for p in trend["points"]]
    assert periods == sorted(periods)
    values = [p["value"] for p in trend["points"]]
    # Strictly increasing per the seeded payload.
    assert values == sorted(values)
    assert values[-1] == pytest.approx(81.2)

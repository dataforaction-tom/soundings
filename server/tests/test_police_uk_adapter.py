"""Integration tests for PoliceUkAdapter.

Centroid-proximate crime aggregation: the adapter takes an LTLA's
geographic centroid, queries data.police.uk for crimes within ~1 mile
for the rolling 12 months, sums them, and rate-converts using
`population.total` for the same place. The fixed methodology caveat
is asserted explicitly so a future refactor removing it fails CI.
"""

import httpx
import pytest
from sqlalchemy import text

from soundings.adapters.police_uk.adapter import (
    METHODOLOGY_CAVEAT,
    PoliceUkAdapter,
)
from soundings.adapters.police_uk.client import PoliceUkClient
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_place_and_population(
    *,
    place_id: str = "ltla24:E06000004",
    code: str = "E06000004",
    name: str = "Stockton-on-Tees",
    population: float = 200_000.0,
) -> None:
    """Seed the bare minimum: one LTLA with a geometry inside it and a
    matching `population.total` value. The geometry is a tiny square
    around (-1.32, 54.57) — Stockton-on-Tees-ish — so ST_Centroid sits
    inside it."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name, geom) "
                "VALUES (:id, 'ltla24', :code, :name, "
                "ST_Multi(ST_GeomFromText("
                "'POLYGON((-1.34 54.55, -1.30 54.55, -1.30 54.59, -1.34 54.59, -1.34 54.55))',"
                " 4326)))"
            ),
            {"id": place_id, "code": code, "name": name},
        )
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, publisher_url, "
                "dataset_url, licence, mode, rate_limit) VALUES "
                "('police_uk', 'data.police.uk', 'Home Office', "
                "'https://data.police.uk/', 'https://data.police.uk/docs/', "
                "'OGL-UK-3.0', 'passthrough', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO data.indicator_value "
                "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) "
                "VALUES (:pid, 'population.total', '2024', :val, "
                "'ons.mid_year_estimates', NOW(), '[]'::jsonb) "
                "ON CONFLICT DO NOTHING"
            ),
            {"pid": place_id, "val": population},
        )


def _crime_record(month: str) -> dict[str, object]:
    return {
        "category": "all-crime",
        "location": {"latitude": "54.5705", "longitude": "-1.3198"},
        "month": month,
    }


async def test_fetch_indicator_aggregates_12_months_into_per_1000_rate() -> None:
    await _seed_place_and_population(population=200_000.0)

    months_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/crime-last-updated" in url:
            return httpx.Response(200, json={"date": "2026-03-01"})
        # crimes-street/all-crime endpoint — return 5 crimes per month called.
        month = request.url.params.get("date") or "unknown"
        months_seen.append(month)
        return httpx.Response(200, json=[_crime_record(month) for _ in range(5)])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = PoliceUkClient(http_client=http)
        adapter = PoliceUkAdapter(get_engine(), police_client=client)
        iv = await adapter.fetch_indicator(
            "crime.recorded_crime_rate", "ltla24:E06000004", period=None
        )

    assert iv is not None
    # 12 months * 5 crimes = 60 crimes. Rate = 60 / 200_000 * 1000 = 0.3.
    assert iv.value == pytest.approx(0.3)
    assert iv.unit == "per 1,000 population"
    assert iv.period == "2026-03"
    assert iv.source.source_id == "police_uk"
    assert len(months_seen) == 12
    # Walks back from the latest available month — earliest is 2025-04.
    assert "2025-04" in months_seen
    assert "2026-03" in months_seen


async def test_fetch_indicator_carries_methodology_caveat() -> None:
    """Every returned value must carry the fixed methodology caveat.

    The string is asserted character-for-character so a refactor that
    softens or removes it fails CI rather than silently dropping the
    provenance signal."""
    await _seed_place_and_population()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/crime-last-updated" in url:
            return httpx.Response(200, json={"date": "2026-03-01"})
        return httpx.Response(200, json=[_crime_record("2026-03")])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = PoliceUkClient(http_client=http)
        adapter = PoliceUkAdapter(get_engine(), police_client=client)
        iv = await adapter.fetch_indicator(
            "crime.recorded_crime_rate", "ltla24:E06000004", period=None
        )

    assert iv is not None
    assert METHODOLOGY_CAVEAT in iv.caveats
    assert "centroid-proximate" in METHODOLOGY_CAVEAT
    assert "~1 mile" in METHODOLOGY_CAVEAT


async def test_violence_indicator_queries_violence_category() -> None:
    await _seed_place_and_population()
    paths_seen: set[str] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/crime-last-updated" in url:
            return httpx.Response(200, json={"date": "2026-03-01"})
        paths_seen.add(request.url.path)
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = PoliceUkClient(http_client=http)
        adapter = PoliceUkAdapter(get_engine(), police_client=client)
        await adapter.fetch_indicator("crime.violence_rate", "ltla24:E06000004", period=None)

    assert any(p.endswith("/crimes-street/violence-and-sexual-offences") for p in paths_seen)


async def test_fetch_indicator_returns_none_without_population() -> None:
    """No population row → no rate possible → no-data."""
    await _seed_place_and_population()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))

    transport = httpx.MockTransport(
        lambda req: (
            httpx.Response(200, json={"date": "2026-03-01"})
            if "/crime-last-updated" in str(req.url)
            else httpx.Response(200, json=[])
        ),
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = PoliceUkClient(http_client=http)
        adapter = PoliceUkAdapter(get_engine(), police_client=client)
        iv = await adapter.fetch_indicator(
            "crime.recorded_crime_rate", "ltla24:E06000004", period=None
        )

    assert iv is None


async def test_fetch_indicator_returns_none_without_centroid() -> None:
    """No geom on the place row → no centroid → no-data."""
    await _seed_place_and_population()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE geography.place SET geom = NULL"))

    transport = httpx.MockTransport(
        lambda req: (
            httpx.Response(200, json={"date": "2026-03-01"})
            if "/crime-last-updated" in str(req.url)
            else httpx.Response(200, json=[])
        ),
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = PoliceUkClient(http_client=http)
        adapter = PoliceUkAdapter(get_engine(), police_client=client)
        iv = await adapter.fetch_indicator(
            "crime.recorded_crime_rate", "ltla24:E06000004", period=None
        )
    assert iv is None


async def test_unknown_indicator_returns_none() -> None:
    await _seed_place_and_population()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    async with httpx.AsyncClient(transport=transport) as http:
        client = PoliceUkClient(http_client=http)
        adapter = PoliceUkAdapter(get_engine(), police_client=client)
        iv = await adapter.fetch_indicator("crime.does_not_exist", "ltla24:E06000004", period=None)
    assert iv is None


async def test_second_fetch_uses_cache() -> None:
    await _seed_place_and_population()
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        url = str(request.url)
        if "/crime-last-updated" in url:
            return httpx.Response(200, json={"date": "2026-03-01"})
        call_count += 1
        return httpx.Response(200, json=[_crime_record("2026-03")])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = PoliceUkClient(http_client=http)
        adapter = PoliceUkAdapter(get_engine(), police_client=client)
        first = await adapter.fetch_indicator(
            "crime.recorded_crime_rate", "ltla24:E06000004", period=None
        )
        first_count = call_count
        second = await adapter.fetch_indicator(
            "crime.recorded_crime_rate", "ltla24:E06000004", period=None
        )

    assert first is not None
    assert second is not None
    assert second.value == first.value
    # 12 calls on first miss, 0 on second hit.
    assert first_count == 12
    assert call_count == 12

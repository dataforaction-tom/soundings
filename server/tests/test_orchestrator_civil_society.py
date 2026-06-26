"""Integration test for IndicatorOrchestrator.compute_civil_society_profile.

Seeds a single LTLA with 6 charities spanning the income brackets, then
asserts the returned profile matches what hand-calculation says it
should be.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text

from soundings.contracts.civil_society import CivilSocietyProfile
from soundings.db.engine import get_engine
from soundings.orchestration.orchestrator import IndicatorOrchestrator
from soundings.orchestration.registry import AdapterRegistry

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _cleanup() -> AsyncIterator[None]:
    engine = get_engine()
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.organisation_operates_in"))
        await conn.execute(text("DELETE FROM data.organisation"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place"))


async def _seed_six_charities() -> None:
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES (:id, 'ltla24', :c, 'Test Place')"
            ),
            {"id": "ltla24:T01", "c": "T01"},
        )
        # 6 charities with assorted incomes + registration years; one removed.
        rows = [
            ("c1", 5_000.0, "2018-01-01", None),
            ("c2", 9_000.0, "2019-04-04", None),
            ("c3", 75_000.0, "2020-06-15", None),
            ("c4", 800_000.0, "2021-09-20", None),
            ("c5", 4_000_000.0, "2015-02-10", None),
            ("c6", 12_000.0, "2010-03-12", "2022-08-01"),  # removed
        ]
        for cid, income, reg, removal in rows:
            raw = {
                "name": cid.upper(),
                "registration_number": cid,
                "latest_income": income,
                "date_of_registration": reg,
                "date_of_removal": removal,
            }
            await conn.execute(
                text(
                    "INSERT INTO data.organisation "
                    "(id, name, classification, source_id, retrieved_at, raw) "
                    "VALUES (:id, :n, ARRAY[]::varchar[], 'charity_commission', :r, "
                    " CAST(:raw AS jsonb))"
                ),
                {"id": cid, "n": cid.upper(), "r": now, "raw": __import__("json").dumps(raw)},
            )
            await conn.execute(
                text(
                    "INSERT INTO data.organisation_operates_in "
                    "(organisation_id, place_id) VALUES (:o, 'ltla24:T01')"
                ),
                {"o": cid},
            )


async def _seed_classified_charities() -> None:
    """Three charities operating in one place: two food/poverty causes, one art."""
    import json

    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:T02', 'ltla24', 'T02', 'Test Place 2')"
            )
        )
        rows = [
            ("f1", 8_000.0, ["Relief of poverty through a community food bank"]),
            ("f2", 50_000.0, ["Tackling food poverty and hunger in the area"]),
            ("u1", 30_000.0, ["Promotion of the arts and music"]),
        ]
        for cid, income, classification in rows:
            raw = {
                "name": cid.upper(),
                "latest_income": income,
                "date_of_registration": "2020-01-01",
            }
            await conn.execute(
                text(
                    "INSERT INTO data.organisation "
                    "(id, name, classification, source_id, retrieved_at, raw) "
                    "VALUES (:id, :n, :cls, 'charity_commission', :r, CAST(:raw AS jsonb))"
                ),
                {
                    "id": cid,
                    "n": cid.upper(),
                    "cls": classification,
                    "r": now,
                    "raw": json.dumps(raw),
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO data.organisation_operates_in "
                    "(organisation_id, place_id) VALUES (:o, 'ltla24:T02')"
                ),
                {"o": cid},
            )


async def test_compute_civil_society_profile_filters_by_keywords() -> None:
    await _seed_classified_charities()
    engine = get_engine()
    orch = IndicatorOrchestrator(engine=engine, registry=AdapterRegistry(engine))

    # Unfiltered: all three charities.
    full = await orch.compute_civil_society_profile(place_id="ltla24:T02")
    assert full.total_organisations == 3
    assert full.filter_keywords == []

    # Filtered to food/poverty causes: only the two matching charities, and the
    # income distribution reflects only them.
    filtered = await orch.compute_civil_society_profile(
        place_id="ltla24:T02", keywords=["food", "poverty"]
    )
    assert filtered.total_organisations == 2
    assert filtered.filter_keywords == ["food", "poverty"]
    assert sum(b.count for b in filtered.income_buckets) == 2


async def test_compute_civil_society_profile_aggregates_correctly() -> None:
    await _seed_six_charities()
    engine = get_engine()
    registry = AdapterRegistry(engine)
    orch = IndicatorOrchestrator(engine=engine, registry=registry)

    profile: CivilSocietyProfile = await orch.compute_civil_society_profile(place_id="ltla24:T01")

    # 6 total, all have income on file, one removed.
    assert profile.total_organisations == 6
    assert profile.with_reported_income == 6
    # Median of [5000, 9000, 12000, 75000, 800000, 4000000] = (12000 + 75000) / 2 = 43500.
    assert profile.median_income == pytest.approx(43_500.0)
    # Mean of the same = 816_833.33...
    assert profile.mean_income == pytest.approx(
        (5_000 + 9_000 + 12_000 + 75_000 + 800_000 + 4_000_000) / 6
    )

    # Buckets: <10k (c1, c2) = 2; 10k-100k (c3, c6) = 2; 100k-1m (c4) = 1; 1m-10m (c5) = 1; 10m+ = 0.
    by_label = {b.label: b.count for b in profile.income_buckets}
    assert by_label["<10k"] == 2
    assert by_label["10k-100k"] == 2
    assert by_label["100k-1m"] == 1
    assert by_label["1m-10m"] == 1
    assert by_label["10m+"] == 0

    # Registration cohort: one row per distinct year present in the data,
    # net = registered - removed (so 2022 shows net=-1 from c6's removal).
    by_year = {c.year: c for c in profile.registration_cohort}
    assert by_year[2018].registered == 1
    assert by_year[2018].net == 1
    assert by_year[2022].registered == 0
    assert by_year[2022].removed == 1
    assert by_year[2022].net == -1

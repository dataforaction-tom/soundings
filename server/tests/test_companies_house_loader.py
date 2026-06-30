"""Tests for the Companies House loader.

The streaming-aggregation logic (`_accumulate`, `_rollup_to_ltla`) is pure
and unit-tested here without a DB. The end-to-end indicator UPSERT is an
integration test (see `test_companies_house_loader_integration` below,
marked `integration`).
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from soundings.adapters.companies_house.loader import (
    CompaniesHouseLoader,
    _Agg,
)
from soundings.adapters.postcodes_io.adapter import PostcodesIoAdapter
from soundings.db.engine import get_engine


async def _aiter(items: list[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
    for item in items:
        yield item


def _company(number: str, postcode: str, incorp: str | None) -> dict[str, Any]:
    return {
        "company_number": number,
        "name": f"COMPANY {number}",
        "postcode": postcode,
        "status": "Active",
        "category": "Private Limited Company",
        "incorporation_date": incorp,
        "sic_codes": [],
    }


# --- _accumulate ----------------------------------------------------------


async def test_accumulate_counts_by_normalised_postcode() -> None:
    as_of = date(2026, 6, 30)
    recent = (as_of - timedelta(days=30)).strftime("%d/%m/%Y")
    companies = _aiter(
        [
            _company("1", "DL5 6LA", "01/02/2010"),
            _company("2", "dl56la", recent),  # same postcode, normalised
            _company("3", "", "01/01/2026"),  # no postcode → skipped
        ]
    )
    aggs = await CompaniesHouseLoader._accumulate(companies, as_of=as_of)
    assert set(aggs) == {"DL56LA"}
    assert aggs["DL56LA"].count == 2
    assert aggs["DL56LA"].incorporations_12m == 1  # only the recent one


async def test_accumulate_ignores_unparseable_incorporation_date() -> None:
    as_of = date(2026, 6, 30)
    companies = _aiter([_company("1", "M1 1AA", "garbage")])
    aggs = await CompaniesHouseLoader._accumulate(companies, as_of=as_of)
    assert aggs["M11AA"].count == 1
    assert aggs["M11AA"].incorporations_12m == 0


# --- _rollup_to_ltla ------------------------------------------------------


def test_rollup_to_ltla_aggregates_and_drops_unresolved() -> None:
    aggs = {
        "DL56LA": _Agg(count=2, incorporations_12m=1),
        "DH13AB": _Agg(count=3, incorporations_12m=2),  # also County Durham
        "M11AA": _Agg(count=5, incorporations_12m=0),  # unresolved
    }
    resolved = {
        "DL56LA": "ltla24:E06000047",
        "DH13AB": "ltla24:E06000047",
        "M11AA": None,
    }
    out = CompaniesHouseLoader._rollup_to_ltla(aggs, resolved)
    assert set(out) == {"ltla24:E06000047"}
    assert out["ltla24:E06000047"].count == 5
    assert out["ltla24:E06000047"].incorporations_12m == 3


# --- integration: end-to-end indicator UPSERT -----------------------------


class _StubBulkClient:
    def __init__(self, companies: list[dict[str, Any]]) -> None:
        self._companies = companies

    async def iter_active_companies(self) -> AsyncIterator[dict[str, Any]]:
        for company in self._companies:
            yield company


async def _seed_baseline() -> None:
    """Clean slate + catalogue rows + LTLAs + pre-resolved postcodes +
    population.total, so the loader never needs postcodes.io."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        # Source + new economy indicators (idempotent — also added via YAML).
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, licence, mode, rate_limit) "
                "VALUES ('companies_house', 'Companies House', 'Companies House', "
                "'OGL-UK-3.0', 'loader', '{}'::jsonb) ON CONFLICT (id) DO NOTHING"
            )
        )
        for key, label, unit in [
            ("economy.active_companies_count", "Active companies", "companies"),
            (
                "economy.active_companies_per_1000",
                "Active companies per 1,000",
                "per 1,000 population",
            ),
            ("economy.new_incorporations_12m", "New incorporations (12m)", "companies"),
        ]:
            await conn.execute(
                text(
                    "INSERT INTO catalogue.indicator "
                    "(key, label, unit, higher_is, source_id, available_at, caveats, related_keys) "
                    "VALUES (:k, :l, :u, NULL, 'companies_house', "
                    "ARRAY['ltla24','utla24'], '[]'::jsonb, ARRAY[]::text[]) "
                    "ON CONFLICT (key) DO NOTHING"
                ),
                {"k": key, "l": label, "u": unit},
            )
        for code in ["E06000047", "E08000035"]:
            await conn.execute(
                text(
                    "INSERT INTO geography.place (id, type, code, name) "
                    "VALUES (:id, 'ltla24', :code, :name)"
                ),
                {"id": f"ltla24:{code}", "code": code, "name": f"Place {code}"},
            )
        for postcode, ltla_code in [
            ("DL56LA", "E06000047"),
            ("DH13AB", "E06000047"),
            ("LS11AA", "E08000035"),
            ("ZZ999ZZ", None),
        ]:
            await conn.execute(
                text(
                    "INSERT INTO geography.postcode (postcode, ltla24, retrieved_at) "
                    "VALUES (:p, :ltla, :ret)"
                ),
                {
                    "p": postcode,
                    "ltla": f"ltla24:{ltla_code}" if ltla_code else None,
                    "ret": datetime.now(tz=UTC),
                },
            )
        # population.total for per_1000 (source ons.mid_year_estimates exists).
        for code, pop in [("E06000047", 500000.0), ("E08000035", 800000.0)]:
            await conn.execute(
                text(
                    "INSERT INTO data.indicator_value "
                    "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) "
                    "VALUES (:pid, 'population.total', '2024', :v, "
                    "'ons.mid_year_estimates', :ret, '[]'::jsonb)"
                ),
                {"pid": f"ltla24:{code}", "v": pop, "ret": datetime.now(tz=UTC)},
            )


def _companies() -> list[dict[str, Any]]:
    recent = "01/06/2026"  # within 365d of as_of 2026-06-30
    old = "01/01/2010"
    spec = [
        ("DL5 6LA", recent),
        ("DL5 6LA", old),
        ("DL5 6LA", old),
        ("DH1 3AB", recent),
        ("DH1 3AB", old),
        ("LS1 1AA", recent),
        ("LS1 1AA", recent),
        ("LS1 1AA", old),
        ("LS1 1AA", old),
        ("ZZ99 9ZZ", recent),  # unresolved → excluded
    ]
    return [_company(str(1000 + i), pc, inc) for i, (pc, inc) in enumerate(spec)]


@pytest.mark.integration
async def test_loader_upserts_per_ltla_indicators() -> None:
    await _seed_baseline()
    loader = CompaniesHouseLoader(
        get_engine(),
        bulk_client=_StubBulkClient(_companies()),
        postcodes_io=PostcodesIoAdapter(get_engine(), ttl=timedelta(hours=720)),
        as_of=date(2026, 6, 30),
    )
    result = await loader.load()
    assert result.rows_written == 2  # two resolved LTLAs

    async with get_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT place_id, indicator_key, value FROM data.indicator_value "
                    "WHERE indicator_key LIKE 'economy.%' ORDER BY place_id, indicator_key"
                )
            )
        ).all()
    got = {(r.place_id, r.indicator_key): float(r.value) for r in rows}

    assert got[("ltla24:E06000047", "economy.active_companies_count")] == 5.0
    assert got[("ltla24:E06000047", "economy.new_incorporations_12m")] == 2.0
    assert got[("ltla24:E06000047", "economy.active_companies_per_1000")] == pytest.approx(0.01)
    assert got[("ltla24:E08000035", "economy.active_companies_count")] == 4.0
    assert got[("ltla24:E08000035", "economy.new_incorporations_12m")] == 2.0
    assert got[("ltla24:E08000035", "economy.active_companies_per_1000")] == pytest.approx(0.005)

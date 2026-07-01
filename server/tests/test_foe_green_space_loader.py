"""Tests for the FoE green-space loader."""

from typing import Any

import pytest
from sqlalchemy import text

from soundings.adapters.foe_green_space.loader import (
    SOURCE_ID,
    FoeGreenSpaceLoader,
)
from soundings.db.engine import get_engine

# --- _extract (pure) ------------------------------------------------------


def test_extract_maps_metrics_and_proportions() -> None:
    rows = [
        {
            "LSOA_Code": "E01000001",
            "Unbuffered_GOSpace_Per_Capita": 12.5,
            "Pcnt_PopArea_With_GOSpace_Access": 30.0,  # → 0.30 proportion
        },
        {
            "LSOA_Code": "E01000002",
            "Unbuffered_GOSpace_Per_Capita": None,  # skipped
            "Pcnt_PopArea_With_GOSpace_Access": 50.0,
        },
    ]
    out = list(
        FoeGreenSpaceLoader._extract(
            rows,
            code_col="LSOA_Code",
            place_type="lsoa21",
            metrics={
                "Unbuffered_GOSpace_Per_Capita": "environment.greenspace.area_per_capita",
                "Pcnt_PopArea_With_GOSpace_Access": "environment.greenspace.access_pct",
            },
        )
    )
    assert ("lsoa21:E01000001", "environment.greenspace.area_per_capita", 12.5) in out
    assert ("lsoa21:E01000001", "environment.greenspace.access_pct", 0.30) in out
    # area_per_capita for E01000002 skipped (None); access_pct present.
    assert ("lsoa21:E01000002", "environment.greenspace.access_pct", 0.50) in out
    assert not any(p == "lsoa21:E01000002" and k.endswith("area_per_capita") for p, k, _ in out)


# --- integration: FK-tolerant UPSERT --------------------------------------


class _StubClient:
    def __init__(self, lsoa_rows: list[dict[str, Any]], la_rows: list[dict[str, Any]]) -> None:
        self._lsoa = lsoa_rows
        self._la = la_rows

    async def fetch_workbook(self) -> bytes:
        return b""

    def read_sheet(self, content: bytes, sheet: str):  # type: ignore[no-untyped-def]
        return iter(self._lsoa if sheet.startswith("LSOA") else self._la)


async def _seed() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, licence, mode, rate_limit) "
                "VALUES ('foe.green_space', 'FoE', 'FoE', 'OGL-UK-3.0', 'loader', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        for key, label, unit in [
            ("environment.greenspace.area_per_capita", "Green space per person", "m2 per person"),
            ("environment.greenspace.access_pct", "Access", "proportion"),
            ("environment.greenspace.garden_area_per_capita", "Garden", "m2 per person"),
            ("environment.greenspace.deprivation_score", "GSDI", "score"),
        ]:
            await conn.execute(
                text(
                    "INSERT INTO catalogue.indicator "
                    "(key, label, unit, source_id, available_at, caveats, related_keys) "
                    "VALUES (:k, :l, :u, 'foe.green_space', ARRAY['lsoa21','ltla24'], "
                    "'[]'::jsonb, ARRAY[]::text[]) ON CONFLICT (key) DO NOTHING"
                ),
                {"k": key, "l": label, "u": unit},
            )
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('lsoa21:E01000001', 'lsoa21', 'E01000001', 'LSOA 1'), "
                "       ('ltla24:E09000001', 'ltla24', 'E09000001', 'City of London')"
            )
        )


@pytest.mark.integration
async def test_loader_upserts_known_places_and_skips_unknown() -> None:
    await _seed()
    lsoa_rows = [
        {  # known LSOA → written
            "LSOA_Code": "E01000001",
            "Unbuffered_GOSpace_Per_Capita": 20.0,
            "Pcnt_PopArea_With_GOSpace_Access": 40.0,
        },
        {  # unknown LSOA (not in spine) → skipped
            "LSOA_Code": "E01999999",
            "Unbuffered_GOSpace_Per_Capita": 99.0,
            "Pcnt_PopArea_With_GOSpace_Access": 99.0,
        },
    ]
    la_rows = [
        {
            "LA_Code": "E09000001",
            "Unbuffered_GOSpace_Per_Capita": 100.0,
            "Pcnt_PopArea_With_GOSpace_Access": 12.0,
            "Garden_Area_Per_Capita": 50.0,
            "Green_Space_Deprivation_Score": 3.14,
        }
    ]
    loader = FoeGreenSpaceLoader(get_engine(), client=_StubClient(lsoa_rows, la_rows))
    result = await loader.load()

    async with get_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT place_id, indicator_key, value FROM data.indicator_value "
                    "WHERE source_id = :sid ORDER BY place_id, indicator_key"
                ),
                {"sid": SOURCE_ID},
            )
        ).all()
    got = {(r.place_id, r.indicator_key): float(r.value) for r in rows}

    # Unknown LSOA skipped entirely.
    assert not any(pid == "lsoa21:E01999999" for pid, _ in got)
    # Known LSOA: area + access (access stored as proportion).
    assert got[("lsoa21:E01000001", "environment.greenspace.area_per_capita")] == 20.0
    assert got[("lsoa21:E01000001", "environment.greenspace.access_pct")] == pytest.approx(0.40)
    # LA: all four metrics.
    assert got[("ltla24:E09000001", "environment.greenspace.garden_area_per_capita")] == 50.0
    assert got[("ltla24:E09000001", "environment.greenspace.deprivation_score")] == pytest.approx(
        3.14
    )
    assert result.rows_written == 6  # 2 (lsoa) + 4 (la)

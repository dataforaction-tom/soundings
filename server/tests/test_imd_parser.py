from pathlib import Path

from soundings.adapters.mhclg_imd2025.parser import parse_imd_xlsx

FIXTURE = Path(__file__).parent / "fixtures" / "imd" / "imd2025_sample.xlsx"


def test_parse_imd_xlsx_returns_indicator_rows() -> None:
    rows = parse_imd_xlsx(FIXTURE.read_bytes())
    by_key: dict[tuple[str, str], float] = {(r.lsoa_code, r.indicator_key): r.value for r in rows}
    assert by_key[("E01012018", "deprivation.imd.score")] == 35.5
    assert by_key[("E01012018", "deprivation.imd.decile")] == 3
    assert by_key[("E01012019", "deprivation.imd.income_score")] == 0.10
    assert by_key[("E01000001", "deprivation.idaci")] == 0.02
    assert by_key[("E01000001", "deprivation.idaopi")] == 0.01


def test_parse_imd_xlsx_yields_8_indicators_per_lsoa() -> None:
    rows = parse_imd_xlsx(FIXTURE.read_bytes())
    by_lsoa: dict[str, set[str]] = {}
    for r in rows:
        by_lsoa.setdefault(r.lsoa_code, set()).add(r.indicator_key)
    assert all(len(keys) == 8 for keys in by_lsoa.values())

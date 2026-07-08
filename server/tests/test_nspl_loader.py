"""Unit tests for the NSPL loader mapping/FK-guard and bulk client.

The mapping and CSV-selection logic are pure and tested here without a DB
or network. The end-to-end upsert + utla24 derivation is an integration
concern (a live ~178MB download), out of scope for unit tests.
"""

import io
import zipfile
from datetime import UTC, datetime

import pytest

from soundings.adapters.ons_nspl.client import NsplBulkClient, _find_data_csv
from soundings.adapters.ons_nspl.loader import _map_row

_NOW = datetime(2026, 7, 7, tzinfo=UTC)

# A representative NSPL row (subset of columns).
_ROW = {
    "pcds": "TS1 1AB",
    "lsoa21": "E01012070",
    "msoa21": "E02002559",
    "laua": "E06000002",
    "ward": "E05001585",
    "pcon": "E14001318",
    "rgn": "E12000001",
    "ctry": "E92000001",
    "doterm": "",
}

# Everything in _ROW resolves to a valid prefixed place id.
_VALID = {
    "lsoa21:E01012070",
    "msoa21:E02002559",
    "ltla24:E06000002",
    "ward24:E05001585",
    "westminster_constituency_24:E14001318",
    "region:E12000001",
    "country:E92000001",
}


def test_map_row_prefixes_codes_and_normalises_postcode() -> None:
    mapped = _map_row(_ROW, _VALID, _NOW)
    assert mapped is not None
    assert mapped["postcode"] == "TS11AB"  # normalised: upper, no space
    assert mapped["lsoa21"] == "lsoa21:E01012070"
    assert mapped["ltla24"] == "ltla24:E06000002"
    assert mapped["ward24"] == "ward24:E05001585"
    assert mapped["westminster_constituency_24"] == "westminster_constituency_24:E14001318"
    assert mapped["region"] == "region:E12000001"
    assert mapped["country"] == "country:E92000001"
    assert mapped["retrieved_at"] == _NOW
    assert "utla24" not in mapped  # derived post-load, never mapped here


def test_map_row_fk_guard_nulls_unknown_codes() -> None:
    # A valid set missing the ward and constituency -> those columns null out,
    # the rest stay. This is the FK guard: no code we haven't seeded reaches
    # the upsert as a real (violating) value.
    partial = _VALID - {"ward24:E05001585", "westminster_constituency_24:E14001318"}
    mapped = _map_row(_ROW, partial, _NOW)
    assert mapped is not None
    assert mapped["ward24"] is None
    assert mapped["westminster_constituency_24"] is None
    assert mapped["ltla24"] == "ltla24:E06000002"  # still present


def test_map_row_blank_codes_become_null() -> None:
    row = {**_ROW, "ward": "", "pcon": "   "}
    mapped = _map_row(row, _VALID, _NOW)
    assert mapped is not None
    assert mapped["ward24"] is None
    assert mapped["westminster_constituency_24"] is None


def test_map_row_skips_rows_without_a_postcode() -> None:
    assert _map_row({**_ROW, "pcds": ""}, _VALID, _NOW) is None
    assert _map_row({**_ROW, "pcds": "   "}, _VALID, _NOW) is None


def _zip_with(members: dict[str, str]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_find_data_csv_picks_largest_data_csv_over_documents() -> None:
    archive = _zip_with(
        {
            "Documents/User_Guide.csv": "small guide",
            "Data/NSPL_MAY_2026_UK.csv": "pcds,laua\n" + ("TS1 1AB,E06000002\n" * 50),
        }
    )
    assert _find_data_csv(archive) == "Data/NSPL_MAY_2026_UK.csv"


def test_find_data_csv_raises_when_no_data_csv() -> None:
    archive = _zip_with({"Documents/readme.txt": "no csv here"})
    with pytest.raises(ValueError, match="No NSPL data CSV"):
        _find_data_csv(archive)


async def test_client_iter_rows_over_in_memory_zip() -> None:
    csv_body = "pcds,laua,lsoa21\nTS1 1AB,E06000002,E01012070\nTS1 2CD,E06000002,E01012071\n"
    archive_buf = io.BytesIO()
    with zipfile.ZipFile(archive_buf, "w") as zf:
        zf.writestr("Documents/guide.txt", "ignore me")
        zf.writestr("Data/NSPL_MAY_2026_UK.csv", csv_body)
    archive_bytes = archive_buf.getvalue()

    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=archive_bytes)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = NsplBulkClient(http_client=http_client, url="https://example.test/nspl.zip")
        rows = [r async for r in client.iter_rows()]

    assert [r["pcds"] for r in rows] == ["TS1 1AB", "TS1 2CD"]
    assert rows[0]["laua"] == "E06000002"

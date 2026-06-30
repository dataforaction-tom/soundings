"""Unit tests for the Friends of the Earth green-space xlsx client."""

import io

import openpyxl

from soundings.adapters.foe_green_space.client import FoeGreenSpaceClient


def _xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "LSOAs V2.1"
    # Mirror the real layout: a leading index column, then code/name, metrics.
    ws.append(
        [
            None,
            "LSOA_Code",
            "LSOA_Name",
            "Unbuffered_GOSpace_Per_Capita",
            "Pcnt_PopArea_With_GOSpace_Access",
        ]
    )
    ws.append([1, "E01000001", "City of London 001A", 12.5, 30.0])
    ws.append([2, "E01000002", "City of London 001B", 8.25, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_read_sheet_maps_columns_by_name() -> None:
    client = FoeGreenSpaceClient()
    rows = list(client.read_sheet(_xlsx_bytes(), "LSOAs V2.1"))
    assert len(rows) == 2
    first = rows[0]
    assert first["LSOA_Code"] == "E01000001"
    assert first["Unbuffered_GOSpace_Per_Capita"] == 12.5
    assert first["Pcnt_PopArea_With_GOSpace_Access"] == 30.0
    # Missing values come through as None, not skipped.
    assert rows[1]["Pcnt_PopArea_With_GOSpace_Access"] is None


def test_read_sheet_strips_header_whitespace() -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S"
    ws.append([" LSOA_Code ", "Unbuffered_GOSpace_Per_Capita"])
    ws.append(["E01000001", 5.0])
    buf = io.BytesIO()
    wb.save(buf)
    rows = list(FoeGreenSpaceClient().read_sheet(buf.getvalue(), "S"))
    assert rows[0]["LSOA_Code"] == "E01000001"

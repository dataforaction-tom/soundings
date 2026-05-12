"""Tests for CharityCommissionBulkClient.

The client downloads the Charity Commission's monthly
`publicextract.charity.zip` (Azure-blob-hosted), unzips its single
tab-delimited file `publicextract.charity.txt`, and yields one dict
per active main-entry charity (`linked_charity_number = '0'` AND
`charity_registration_status = 'Registered'`).

These tests build a synthetic ZIP in memory via `zipfile.ZipFile` over
`io.BytesIO` and serve it through `httpx.MockTransport`. No network.
"""

import csv
import io
import zipfile

import httpx
import pytest

from soundings.adapters.charity_commission.client import (
    CC_CHARITY_BULK_URL,
    CharityCommissionBulkClient,
)

# The full column list lifted from the live charity.txt — keeping it
# accurate ensures the DictReader merges cleanly when the real bulk
# is structured slightly differently per month.
CC_COLUMNS = [
    "date_of_extract",
    "organisation_number",
    "registered_charity_number",
    "linked_charity_number",
    "charity_name",
    "charity_type",
    "charity_registration_status",
    "date_of_registration",
    "date_of_removal",
    "charity_reporting_status",
    "latest_acc_fin_period_start_date",
    "latest_acc_fin_period_end_date",
    "latest_income",
    "latest_expenditure",
    "charity_contact_address1",
    "charity_contact_address2",
    "charity_contact_address3",
    "charity_contact_address4",
    "charity_contact_address5",
    "charity_contact_postcode",
    "charity_contact_phone",
    "charity_contact_email",
    "charity_contact_web",
    "charity_company_registration_number",
    "charity_insolvent",
    "charity_in_administration",
    "charity_previously_excepted",
    "charity_is_cdf_or_cif",
    "charity_is_cio",
    "cio_is_dissolved",
    "date_cio_dissolution_notice",
    "charity_activities",
    "charity_gift_aid",
    "charity_has_land",
]


def _build_zip(rows: list[dict[str, str]]) -> bytes:
    """Serialise a fake bulk archive shaped like the real CC zip:
    single file `publicextract.charity.txt`, tab-delimited, with the
    full column header."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=CC_COLUMNS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            full = {col: row.get(col, "") for col in CC_COLUMNS}
            writer.writerow(full)
        zf.writestr("publicextract.charity.txt", text.getvalue())
    return buf.getvalue()


async def test_client_yields_active_main_charities() -> None:
    """Filters: linked_charity_number='0' AND charity_registration_status='Registered'."""
    zip_bytes = _build_zip(
        [
            {
                "registered_charity_number": "202918",
                "linked_charity_number": "0",
                "charity_name": "OXFAM",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "OX4 2JY",
                "charity_activities": "Relief of poverty worldwide",
            },
            {
                "registered_charity_number": "1156580",
                "linked_charity_number": "0",
                "charity_name": "ANOTHER",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "TS18 1AB",
                "charity_activities": "Youth education",
            },
            {
                # Subsidiary entry — should be filtered out.
                "registered_charity_number": "202918",
                "linked_charity_number": "1",
                "charity_name": "OXFAM SHOP X",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "OX1 1AA",
                "charity_activities": "",
            },
            {
                # Removed main entry — should be filtered out.
                "registered_charity_number": "999999",
                "linked_charity_number": "0",
                "charity_name": "REMOVED",
                "charity_registration_status": "Removed",
                "charity_contact_postcode": "XX0 0XX",
                "charity_activities": "",
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CC_CHARITY_BULK_URL
        return httpx.Response(200, content=zip_bytes)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = CharityCommissionBulkClient(http_client=http)
        rows = [row async for row in client.iter_active_charities()]

    assert len(rows) == 2
    by_id = {r["registration_number"]: r for r in rows}
    assert by_id["202918"]["name"] == "OXFAM"
    assert by_id["202918"]["postcode"] == "OX4 2JY"
    assert by_id["202918"]["status"] == "Registered"
    assert by_id["202918"]["classification"] == ["Relief of poverty worldwide"]
    assert by_id["1156580"]["postcode"] == "TS18 1AB"
    assert "OXFAM SHOP X" not in {r["name"] for r in rows}
    assert "REMOVED" not in {r["name"] for r in rows}


async def test_client_handles_empty_activities() -> None:
    zip_bytes = _build_zip(
        [
            {
                "registered_charity_number": "1",
                "linked_charity_number": "0",
                "charity_name": "ONE",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "AB1 1AB",
                "charity_activities": "",
            }
        ]
    )
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=zip_bytes))
    async with httpx.AsyncClient(transport=transport) as http:
        client = CharityCommissionBulkClient(http_client=http)
        rows = [row async for row in client.iter_active_charities()]
    assert rows[0]["classification"] == []


async def test_client_skips_rows_with_blank_registration_number() -> None:
    """Defensive — every legitimate CC row has a registration number,
    but a malformed bulk shouldn't crash the loader."""
    zip_bytes = _build_zip(
        [
            {
                "registered_charity_number": "",
                "linked_charity_number": "0",
                "charity_name": "NO REG",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "AB1 1AB",
            },
            {
                "registered_charity_number": "100",
                "linked_charity_number": "0",
                "charity_name": "OK",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "AB1 1AB",
            },
        ]
    )
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=zip_bytes))
    async with httpx.AsyncClient(transport=transport) as http:
        client = CharityCommissionBulkClient(http_client=http)
        rows = [row async for row in client.iter_active_charities()]
    assert [r["registration_number"] for r in rows] == ["100"]


async def test_client_raises_on_http_error() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(503))
    async with httpx.AsyncClient(transport=transport) as http:
        client = CharityCommissionBulkClient(http_client=http)
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in client.iter_active_charities():
                pass

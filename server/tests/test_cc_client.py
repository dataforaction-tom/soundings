"""Tests for CharityCommissionBulkClient.

The client streams the Charity Commission bulk register ZIP from
<https://register-of-charities.charitycommission.gov.uk/register/full-register-download>,
merges the two CSVs we care about (`charity` for the core entity,
`charity_main_charity` for status + address), and yields one dict per
active charity. Anonymous — no API key.

These tests build a synthetic ZIP in memory via `zipfile.ZipFile` over
`io.BytesIO` and serve it through `httpx.MockTransport`. No network.
"""

import csv
import io
import zipfile

import httpx
import pytest

from soundings.adapters.charity_commission.client import (
    CC_BULK_URL,
    CharityCommissionBulkClient,
)


def _build_zip(*, charity_rows: list[dict[str, str]], main_rows: list[dict[str, str]]) -> bytes:
    """Serialise a fake bulk archive with the two CSVs the client merges on."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # charity.csv — registration_number, charity_name, classification
        charity_fields = ["registration_number", "charity_name", "classification"]
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=charity_fields)
        writer.writeheader()
        for row in charity_rows:
            writer.writerow({k: row.get(k, "") for k in charity_fields})
        zf.writestr("publicextract.charity.csv", text.getvalue())

        # charity_main_charity.csv — registration_number, status, postcode
        main_fields = [
            "registration_number",
            "charity_registration_status",
            "charity_contact_postcode",
        ]
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=main_fields)
        writer.writeheader()
        for row in main_rows:
            writer.writerow({k: row.get(k, "") for k in main_fields})
        zf.writestr("publicextract.charity_main_charity.csv", text.getvalue())
    return buf.getvalue()


async def test_client_streams_active_charities_from_bulk_zip() -> None:
    """Happy path: bulk ZIP unpacks, the two CSVs merge on
    registration_number, only active charities are yielded."""
    zip_bytes = _build_zip(
        charity_rows=[
            {"registration_number": "202918", "charity_name": "OXFAM", "classification": "1,12"},
            {"registration_number": "1156580", "charity_name": "ANOTHER", "classification": "3"},
            {"registration_number": "999999", "charity_name": "REMOVED", "classification": ""},
        ],
        main_rows=[
            {
                "registration_number": "202918",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "OX4 2JY",
            },
            {
                "registration_number": "1156580",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "TS18 1AB",
            },
            {
                "registration_number": "999999",
                "charity_registration_status": "Removed",
                "charity_contact_postcode": "XX0 0XX",
            },
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CC_BULK_URL
        return httpx.Response(
            200,
            content=zip_bytes,
            headers={"Content-Type": "application/zip"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = CharityCommissionBulkClient(http_client=http)
        rows = [row async for row in client.iter_active_charities()]

    # Only the two "Registered" entries; the "Removed" row is filtered.
    assert len(rows) == 2
    by_id = {r["registration_number"]: r for r in rows}
    assert by_id["202918"]["name"] == "OXFAM"
    assert by_id["202918"]["postcode"] == "OX4 2JY"
    assert by_id["202918"]["status"] == "Registered"
    # Classification is split into a list of codes.
    assert by_id["202918"]["classification"] == ["1", "12"]
    assert by_id["1156580"]["postcode"] == "TS18 1AB"
    # Removed row must not appear.
    assert "999999" not in by_id


async def test_client_yields_empty_classification_when_blank() -> None:
    zip_bytes = _build_zip(
        charity_rows=[{"registration_number": "1", "charity_name": "ONE", "classification": ""}],
        main_rows=[
            {
                "registration_number": "1",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "AB1 1AB",
            }
        ],
    )

    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=zip_bytes))
    async with httpx.AsyncClient(transport=transport) as http:
        client = CharityCommissionBulkClient(http_client=http)
        rows = [row async for row in client.iter_active_charities()]
    assert rows[0]["classification"] == []


async def test_client_handles_orphan_charity_row_without_main_entry() -> None:
    """If the `charity` table has a row but the `charity_main_charity`
    join misses, we treat it as missing status / postcode rather than
    raising. Keeps a partial-archive parse moving."""
    zip_bytes = _build_zip(
        charity_rows=[
            {"registration_number": "42", "charity_name": "ORPHAN", "classification": "1"}
        ],
        main_rows=[],  # no main row for reg 42
    )
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=zip_bytes))
    async with httpx.AsyncClient(transport=transport) as http:
        client = CharityCommissionBulkClient(http_client=http)
        rows = [row async for row in client.iter_active_charities()]
    # Orphan rows aren't active (no status), so they're filtered out.
    assert rows == []


async def test_client_raises_on_http_error() -> None:
    """Network/upstream failures bubble up — the loader decides how to
    handle them. We don't swallow."""
    transport = httpx.MockTransport(lambda req: httpx.Response(503))
    async with httpx.AsyncClient(transport=transport) as http:
        client = CharityCommissionBulkClient(http_client=http)
        with pytest.raises(httpx.HTTPStatusError):
            async for _ in client.iter_active_charities():
                pass

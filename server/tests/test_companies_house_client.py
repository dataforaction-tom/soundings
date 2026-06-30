"""Unit tests for the Companies House bulk CSV client."""

import io
import zipfile

import httpx

from soundings.adapters.companies_house.client import (
    CompaniesHouseBulkClient,
    bulk_part_urls,
)

# Real CH free-data headers are comma-delimited with dotted names and, in
# practice, stray leading spaces after the comma (e.g. " CompanyNumber").
HEADER = (
    "CompanyName, CompanyNumber,RegAddress.PostCode,CompanyCategory,"
    "CompanyStatus,IncorporationDate,SICCode.SicText_1"
)
ROWS = [
    "ACME LTD,01234567,DL5 6LA,Private Limited Company,Active,01/02/2010,"
    "62012 - Business and domestic software development",
    "DEAD LTD,07654321,M1 1AA,Private Limited Company,Dissolved,01/02/2000,",
    "GAMMA LLP,OC399999,LS1 1AA,Limited Liability Partnership,Active,15/06/2024,",
]


def _zip_bytes(header: str, rows: list[str], *, name: str = "part.csv") -> bytes:
    csv_text = header + "\r\n" + "\r\n".join(rows) + "\r\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(name, csv_text.encode("utf-8"))
    return buf.getvalue()


async def test_iter_active_companies_yields_active_only_with_mapped_fields() -> None:
    payload = _zip_bytes(HEADER, ROWS)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ch = CompaniesHouseBulkClient(http_client=client, urls=["https://example.test/part.zip"])
        out = [c async for c in ch.iter_active_companies()]

    # Dissolved company skipped; active ones mapped.
    assert [c["company_number"] for c in out] == ["01234567", "OC399999"]
    acme = out[0]
    assert acme["name"] == "ACME LTD"
    assert acme["postcode"] == "DL5 6LA"
    assert acme["status"] == "Active"
    assert acme["category"] == "Private Limited Company"
    assert acme["incorporation_date"] == "01/02/2010"
    assert acme["sic_codes"] == ["62012"]


async def test_iter_active_companies_spans_multiple_parts() -> None:
    part1 = _zip_bytes(HEADER, [ROWS[0]])
    part2 = _zip_bytes(HEADER, [ROWS[2]])
    by_url = {
        "https://example.test/part1.zip": part1,
        "https://example.test/part2.zip": part2,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=by_url[str(request.url)])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ch = CompaniesHouseBulkClient(http_client=client, urls=list(by_url))
        out = [c async for c in ch.iter_active_companies()]

    assert [c["company_number"] for c in out] == ["01234567", "OC399999"]


def test_bulk_part_urls_builds_seven_dated_parts() -> None:
    from datetime import date

    urls = bulk_part_urls(date(2026, 6, 9))
    assert len(urls) == 7
    assert urls[0] == (
        "https://download.companieshouse.gov.uk/BasicCompanyData-2026-06-01-part1_7.zip"
    )
    assert urls[-1].endswith("part7_7.zip")

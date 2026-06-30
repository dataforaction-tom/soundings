"""Companies House — Free Company Data Product bulk client.

Downloads the monthly bulk product and yields one dict per *active*
company. Anonymous — no API key. The product is published as seven
date-stamped split ZIPs (~67MB each) within ~5 working days of month
end; we iterate the parts one at a time so peak memory stays bounded to
a single part rather than the ~470MB whole-file download.

Why bulk, not the REST API: the Companies House Advanced Search API has
no postcode/region/local-authority filter (only a fuzzy free-text
`location`), so it cannot enumerate companies for an ONS LTLA. With no
area-search endpoint and a monthly cadence, the bulk product is the
documented carve-out from the API-first principle — the same situation
as the Charity Commission loader. See
`docs/plans/2026-06-30-companies-house-loader-plan.md`.

CSV shape: comma-delimited, header row with dotted names
(`RegAddress.PostCode`, `SICCode.SicText_1`...). In practice the real
header carries stray leading spaces after commas, so we strip field
names before mapping.
"""

import csv
import io
import zipfile
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import httpx

# CH free-text SIC columns and address lines can exceed Python's default
# 128KB csv.field_size_limit. 16MB is comfortably above any single field.
csv.field_size_limit(16 * 1024 * 1024)

DOWNLOAD_HOST = "https://download.companieshouse.gov.uk"
NUM_PARTS = 7


def bulk_part_urls(as_of: date) -> list[str]:
    """The seven split-file URLs for the bulk product as published in
    `as_of`'s month. The product is date-stamped with the first of the
    month (`BasicCompanyData-YYYY-MM-01-part{n}_7.zip`)."""
    stamp = f"{as_of.year:04d}-{as_of.month:02d}-01"
    return [
        f"{DOWNLOAD_HOST}/BasicCompanyData-{stamp}-part{n}_{NUM_PARTS}.zip"
        for n in range(1, NUM_PARTS + 1)
    ]


class CompaniesHouseBulkClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        urls: list[str] | None = None,
        *,
        as_of: date | None = None,
    ) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._urls = urls
        self._as_of = as_of

    def _resolve_urls(self) -> list[str]:
        if self._urls is not None:
            return self._urls
        if self._as_of is None:
            raise ValueError("CompaniesHouseBulkClient needs either urls or as_of")
        return bulk_part_urls(self._as_of)

    async def iter_active_companies(self) -> AsyncIterator[dict[str, Any]]:
        """Yield one dict per active company across all bulk parts.

        Each yielded dict has stable keys: `company_number`, `name`,
        `postcode`, `status`, `category`, `incorporation_date` (raw
        DD/MM/YYYY string), `sic_codes` (list[str] of leading codes).
        """
        client = self._client or httpx.AsyncClient(timeout=300.0)
        try:
            for url in self._resolve_urls():
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
                archive = zipfile.ZipFile(io.BytesIO(response.content))
                # One CSV per part ZIP.
                csv_name = archive.namelist()[0]
                with archive.open(csv_name) as fh:
                    text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
                    reader = csv.DictReader(text)
                    if reader.fieldnames:
                        reader.fieldnames = [name.strip() for name in reader.fieldnames]
                    for row in reader:
                        company = _map_row(row)
                        if company is not None:
                            yield company
        finally:
            if self._owns_client:
                await client.aclose()


def _map_row(row: dict[str, str]) -> dict[str, Any] | None:
    if (row.get("CompanyStatus", "") or "").strip() != "Active":
        return None
    number = (row.get("CompanyNumber", "") or "").strip()
    if not number:
        return None
    return {
        "company_number": number,
        "name": (row.get("CompanyName", "") or "").strip(),
        "postcode": (row.get("RegAddress.PostCode", "") or "").strip(),
        "status": "Active",
        "category": (row.get("CompanyCategory", "") or "").strip(),
        "incorporation_date": (row.get("IncorporationDate", "") or "").strip() or None,
        "sic_codes": _sic_codes(row),
    }


def _sic_codes(row: dict[str, str]) -> list[str]:
    """Extract the leading numeric SIC code from each populated
    `SICCode.SicText_n` column (values look like
    '62012 - Business and domestic software development')."""
    codes: list[str] = []
    for n in range(1, 5):
        raw = (row.get(f"SICCode.SicText_{n}", "") or "").strip()
        if not raw:
            continue
        code = raw.split(" - ", 1)[0].strip()
        if code:
            codes.append(code)
    return codes

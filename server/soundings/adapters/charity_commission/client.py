"""Charity Commission for England and Wales — bulk register client.

Downloads the public monthly bulk register ZIP and yields one merged
dict per active charity. Anonymous (no API key); CC publishes the
download at the URL below.

The API alternative is detail-lookup-only (no search-by-area endpoint),
so for Phase 4 the bulk download is the documented carve-out from the
project's API-first principle. See
`docs/plans/2026-05-12-soundings-v1-phase-4-plan.md` for the rationale.

The archive contains several CSVs. We merge two:

- `publicextract.charity.csv` — core entity table (name, classification)
- `publicextract.charity_main_charity.csv` — status + contact postcode

Streaming notes: the archive is ~50MB compressed; we hold the full
bytes in memory because the ZIP central-directory is at the end (so a
truly-streaming parser would need a seekable underlying source).
Decoded row-by-row, not all rows in memory at once.
"""

import csv
import io
import zipfile
from collections.abc import AsyncIterator
from typing import Any

import httpx

CC_BULK_URL = (
    "https://register-of-charities.charitycommission.gov.uk/register/full-register-download"
)

CHARITY_CSV = "publicextract.charity.csv"
MAIN_CSV = "publicextract.charity_main_charity.csv"


class CharityCommissionBulkClient:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client
        self._owns_client = http_client is None

    async def iter_active_charities(self) -> AsyncIterator[dict[str, Any]]:
        """Yield one merged row per active (status='Registered') charity.

        Each yielded dict has stable keys: registration_number, name,
        postcode, status, classification (list[str]).
        """
        client = self._client or httpx.AsyncClient(timeout=120.0)
        try:
            response = await client.get(CC_BULK_URL, follow_redirects=True)
            response.raise_for_status()
            archive = zipfile.ZipFile(io.BytesIO(response.content))

            # Build the status/postcode side-table first so the merge is
            # one pass over the larger `charity` table.
            main_by_reg: dict[str, dict[str, str]] = {}
            with archive.open(MAIN_CSV) as main_fh:
                text = io.TextIOWrapper(main_fh, encoding="utf-8", newline="")
                for row in csv.DictReader(text):
                    reg = row.get("registration_number", "").strip()
                    if not reg:
                        continue
                    main_by_reg[reg] = row

            with archive.open(CHARITY_CSV) as charity_fh:
                text = io.TextIOWrapper(charity_fh, encoding="utf-8", newline="")
                for row in csv.DictReader(text):
                    reg = row.get("registration_number", "").strip()
                    main = main_by_reg.get(reg)
                    if main is None:
                        continue  # orphan: no main_charity row → skip
                    status = main.get("charity_registration_status", "").strip()
                    if status != "Registered":
                        continue
                    yield {
                        "registration_number": reg,
                        "name": row.get("charity_name", "").strip(),
                        "postcode": main.get("charity_contact_postcode", "").strip(),
                        "status": status,
                        "classification": _split_classification(row.get("classification", "")),
                    }
        finally:
            if self._owns_client:
                await client.aclose()


def _split_classification(raw: str) -> list[str]:
    """CC publishes classification as a comma-separated list of codes."""
    if not raw:
        return []
    return [code.strip() for code in raw.split(",") if code.strip()]

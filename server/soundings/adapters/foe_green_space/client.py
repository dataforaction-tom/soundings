"""Friends of the Earth — Green Space Consolidated Data client.

Downloads the consolidated green-space workbook (.xlsx) and reads a named
sheet. The workbook carries LSOA, MSOA, and Local Authority sheets; the
loader reads the LSOA and LA sheets. Open Government Licence v3.0 / Open
Parliament Licence (per FoE's near-you data portal).

The real headers carry a leading index column and occasional stray
whitespace, so we strip header names and key rows by column name.
"""

import io
from collections.abc import Iterator
from typing import Any

import httpx
import openpyxl

FOE_GREENSPACE_URL = (
    "https://cdn.friendsoftheearth.uk/sites/default/files/downloads/"
    "Green%20Space%20Consolidated%20Data%20-%20England%20-%20Version%202.1.xlsx"
)
LSOA_SHEET = "LSOAs V2.1"
LA_SHEET = "Local Authorities V2.1"


class FoeGreenSpaceClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        url: str = FOE_GREENSPACE_URL,
    ) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._url = url

    async def fetch_workbook(self) -> bytes:
        client = self._client or httpx.AsyncClient(timeout=120.0)
        try:
            response = await client.get(self._url, follow_redirects=True)
            response.raise_for_status()
            return response.content
        finally:
            if self._owns_client:
                await client.aclose()

    def read_sheet(self, content: bytes, sheet: str) -> Iterator[dict[str, Any]]:
        """Yield one dict per data row, keyed by (whitespace-stripped) column
        name. Columns with a blank header are dropped."""
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb[sheet]
        rows = ws.iter_rows(values_only=True)
        raw_header = next(rows, None)
        if raw_header is None:
            return
        header = [str(h).strip() if h is not None else None for h in raw_header]
        for row in rows:
            record: dict[str, Any] = {}
            for i in range(min(len(header), len(row))):
                key = header[i]
                if key:
                    record[key] = row[i]
            yield record

"""ONS NSPL — National Statistics Postcode Lookup bulk client.

Downloads the quarterly NSPL ZIP (~178MB) and yields one dict per postcode
row from the single data CSV inside. The download URL is a stable ArcGIS
item `/data` endpoint that 302-redirects to a temporary signed S3 link, so
we follow redirects.

Why bulk, not an API: the NSPL is distributed only as a bulk ZIP (there is
no per-postcode area-search API that returns the full statutory-geography
mapping for ~2.7M postcodes). Loading it once into `geography.postcode`
lets the postcode-based loaders (Companies House, Charity Commission)
resolve postcode -> place in a single indexed lookup instead of hitting the
postcodes.io API. See
`docs/superpowers/specs/2026-07-07-nspl-loader-design.md`.

The ZIP holds the ~1GB uncompressed CSV under `Data/`; we hold the ~178MB
ZIP bytes in memory and stream-decompress the CSV member row by row, so the
uncompressed CSV is never fully materialised.
"""

import csv
import io
import zipfile
from collections.abc import AsyncIterator

import httpx

# NSPL address/name fields are short, but raise the field-size limit anyway
# to stay well clear of Python's 128KB default on any single field.
csv.field_size_limit(16 * 1024 * 1024)


def _find_data_csv(archive: zipfile.ZipFile) -> str:
    """Return the name of the postcode data CSV in the NSPL archive.

    The archive layout is `Data/NSPL_<MON>_<YEAR>_UK.csv` plus a
    `Documents/` folder (user guide, metadata). Pick the largest `.csv`
    that isn't documentation — robust to layout changes between vintages.
    """
    csvs = [
        info
        for info in archive.infolist()
        if info.filename.lower().endswith(".csv") and "document" not in info.filename.lower()
    ]
    if not csvs:
        names = archive.namelist()[:8]
        raise ValueError(f"No NSPL data CSV found in archive members: {names}")
    return max(csvs, key=lambda info: info.file_size).filename


class NsplBulkClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        url: str | None = None,
    ) -> None:
        self._client = http_client
        self._owns_client = http_client is None
        self._url = url

    async def iter_rows(self) -> AsyncIterator[dict[str, str]]:
        """Yield one dict per NSPL row, keyed by the raw NSPL column names
        (`pcds`, `laua`, `lsoa21`, `msoa21`, `ward`, `pcon`, `rgn`,
        `ctry`, ...). Mapping to our schema happens in the loader."""
        if not self._url:
            raise ValueError("NsplBulkClient needs a url")
        client = self._client or httpx.AsyncClient(timeout=600.0)
        try:
            response = await client.get(self._url, follow_redirects=True)
            response.raise_for_status()
            archive = zipfile.ZipFile(io.BytesIO(response.content))
            csv_name = _find_data_csv(archive)
            with archive.open(csv_name) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
                reader = csv.DictReader(text)
                if reader.fieldnames:
                    reader.fieldnames = [name.strip() for name in reader.fieldnames]
                for row in reader:
                    yield row
        finally:
            if self._owns_client:
                await client.aclose()

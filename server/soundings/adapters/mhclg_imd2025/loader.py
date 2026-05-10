"""mhclg.imd2025 loader.

Downloads the IMD 2025 Excel workbook, parses it via `parser.parse_imd_xlsx`,
and upserts the LSOA-level indicators into `data.indicator_value` with
`period = "2025"`. LTLA aggregation is a separate step (Task 19).
"""

from datetime import UTC, datetime

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.base import LoaderAdapter, LoaderResult
from soundings.adapters.mhclg_imd2025.parser import parse_imd_xlsx
from soundings.db.models.data import IndicatorValue

# Pinned in ADR-0002. Treat as unverified until first live load confirms.
IMD_BULK_URL = (
    "https://assets.publishing.service.gov.uk/government/uploads/system/"
    "uploads/attachment_data/file/imd2025/IoD2025_File_2_Domains_of_Deprivation.xlsx"
)
IMD_PERIOD = "2025"


class MhclgImd2025Loader(LoaderAdapter):
    source_id = "mhclg.imd2025"

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        http_client: httpx.AsyncClient | None = None,
        url: str = IMD_BULK_URL,
    ) -> None:
        super().__init__(engine)
        self._client = http_client
        self._url = url

    async def load(self, run_id: str | None = None) -> LoaderResult:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=120.0, follow_redirects=True)
        try:
            response = await client.get(self._url)
            response.raise_for_status()
            blob = response.content
        finally:
            if owns_client:
                await client.aclose()
        return await self.load_from_bytes(blob)

    async def load_from_bytes(self, blob: bytes) -> LoaderResult:
        rows = parse_imd_xlsx(blob)
        if not rows:
            return LoaderResult(rows_written=0)

        retrieved = datetime.now(tz=UTC)
        records = [
            {
                "place_id": f"lsoa21:{r.lsoa_code}",
                "indicator_key": r.indicator_key,
                "period": IMD_PERIOD,
                "value": r.value,
                "source_id": self.source_id,
                "retrieved_at": retrieved,
                "loader_run_id": None,
                "caveats": ["IMD covers England only."],
            }
            for r in rows
        ]
        async with self._engine.begin() as conn:
            stmt = insert(IndicatorValue).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    IndicatorValue.place_id,
                    IndicatorValue.indicator_key,
                    IndicatorValue.period,
                ],
                set_={
                    "value": stmt.excluded.value,
                    "retrieved_at": stmt.excluded.retrieved_at,
                    "source_id": stmt.excluded.source_id,
                },
            )
            await conn.execute(stmt)
        return LoaderResult(rows_written=len(records))

"""mhclg.imd2025 + mhclg.imd2019 loaders.

Downloads the IMD Excel workbook, parses it via `parser.parse_imd_xlsx`, and
upserts the LSOA-level indicators into `data.indicator_value`. LTLA
aggregation is a separate step (see `aggregation.py`).

The 2019 loader is a small subclass that overrides `source_id`, the default
URL, and the period. Both sources coexist — `fetch_indicator(period=None)`
returns the latest period (so 2025 wins by default).
"""

from datetime import UTC, datetime

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.base import LoaderAdapter, LoaderResult
from soundings.adapters.mhclg_imd2025.parser import parse_imd_xlsx
from soundings.db.models.data import IndicatorValue, TrendPoint

# URLs and periods pinned in ADR-0002.
# IMD 2025 splits raw scores into File 5; deciles/ranks live in File 2.
# We load File 5 for scores. Decile-based indicators are not yet wired up
# for the 2025 edition (tracked in PLAN.md).
# IMD 2019 publishes scores + deciles in a single workbook (File 2).
IMD2025_BULK_URL = (
    "https://assets.publishing.service.gov.uk/media/691ded34513046b952c500bd/"
    "File_5_IoD2025_Scores_for_the_Indices_of_Deprivation.xlsx"
)
IMD2019_BULK_URL = (
    "https://assets.publishing.service.gov.uk/media/5d8b3ade40f0b60999a23330/"
    "File_2_-_IoD2019_Domains_of_Deprivation.xlsx"
)


class MhclgImd2025Loader(LoaderAdapter):
    source_id = "mhclg.imd2025"
    default_url = IMD2025_BULK_URL
    period = "2025"

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        http_client: httpx.AsyncClient | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(engine)
        self._client = http_client
        self._url = url or self.default_url

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

    # asyncpg caps a statement at 32_767 placeholders. Each record uses 8
    # columns, so 4_000 rows per batch gives comfortable headroom.
    _INSERT_BATCH_SIZE = 4_000

    async def load_from_bytes(self, blob: bytes) -> LoaderResult:
        rows = parse_imd_xlsx(blob)
        if not rows:
            return LoaderResult(rows_written=0)

        retrieved = datetime.now(tz=UTC)
        records = [
            {
                "place_id": f"lsoa21:{r.lsoa_code}",
                "indicator_key": r.indicator_key,
                "period": self.period,
                "value": r.value,
                "source_id": self.source_id,
                "retrieved_at": retrieved,
                "loader_run_id": None,
                "caveats": ["IMD covers England only."],
            }
            for r in rows
        ]
        # Skip rows whose LSOA isn't in our geography spine. Two cases:
        # (1) a `--light` seed only loaded a subset of LSOAs; (2) MHCLG's
        # workbook references an LSOA boundary version we haven't loaded
        # (notably IMD 2019 uses LSOA 2011 codes). FK to geography.place
        # would reject these anyway — filter explicitly to keep the loader
        # idempotent on partial geographies.
        async with self._engine.connect() as conn:
            existing = {
                row.id
                for row in (
                    await conn.execute(text("SELECT id FROM geography.place WHERE type = 'lsoa21'"))
                ).all()
            }
        records = [r for r in records if r["place_id"] in existing]
        if not records:
            return LoaderResult(rows_written=0, notes="no LSOAs in geography spine match")

        async with self._engine.begin() as conn:
            for start in range(0, len(records), self._INSERT_BATCH_SIZE):
                batch = records[start : start + self._INSERT_BATCH_SIZE]
                stmt = insert(IndicatorValue).values(batch)
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

        # Mirror LSOA-level rows into data.trend_point so get_trend can serve
        # cross-edition trends (2019 + 2025) once both loaders have run.
        trend_records = [
            {
                "place_id": r["place_id"],
                "indicator_key": r["indicator_key"],
                "period": r["period"],
                "value": r["value"],
                "revised": False,
                "source_id": r["source_id"],
                "retrieved_at": r["retrieved_at"],
            }
            for r in records
        ]
        async with self._engine.begin() as conn:
            for start in range(0, len(trend_records), self._INSERT_BATCH_SIZE):
                batch = trend_records[start : start + self._INSERT_BATCH_SIZE]
                tstmt = insert(TrendPoint).values(batch)
                tstmt = tstmt.on_conflict_do_update(
                    index_elements=[
                        TrendPoint.place_id,
                        TrendPoint.indicator_key,
                        TrendPoint.period,
                    ],
                    set_={
                        "value": tstmt.excluded.value,
                        "retrieved_at": tstmt.excluded.retrieved_at,
                        "source_id": tstmt.excluded.source_id,
                    },
                )
                await conn.execute(tstmt)
        return LoaderResult(rows_written=len(records))


class MhclgImd2019Loader(MhclgImd2025Loader):
    source_id = "mhclg.imd2019"
    default_url = IMD2019_BULK_URL
    period = "2019"

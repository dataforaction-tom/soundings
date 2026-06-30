"""FoeGreenSpaceLoader — writes green-space indicators from the FoE
Green Space Consolidated workbook into `data.indicator_value`.

LSOA-level metrics come from the LSOA sheet (filling the neighbourhood
gap), LA-level metrics from the Local Authorities sheet. FK-tolerant:
codes whose `geography.place` row isn't present (e.g. 2011 LSOAs that
changed in 2021, or LA boundary reorganisations) are skipped, mirroring
the IMD loader's pre-filter.
"""

import math
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.base import LoaderAdapter, LoaderResult
from soundings.adapters.foe_green_space.client import (
    LA_SHEET,
    LSOA_SHEET,
    FoeGreenSpaceClient,
)

SOURCE_ID = "foe.green_space"
PERIOD = "2021"  # vintage of the consolidated v2.1 inputs
UPSERT_CHUNK = 2000

# Metrics available at both LSOA and LA level.
_COMMON_METRICS: dict[str, str] = {
    "Unbuffered_GOSpace_Per_Capita": "environment.greenspace.area_per_capita",
    "Pcnt_PopArea_With_GOSpace_Access": "environment.greenspace.access_pct",
}
# Metrics only present on the Local Authorities sheet.
_LA_ONLY_METRICS: dict[str, str] = {
    "Garden_Area_Per_Capita": "environment.greenspace.garden_area_per_capita",
    "Green_Space_Deprivation_Score": "environment.greenspace.deprivation_score",
}
# Indicators stored as a 0-1 proportion (source column is a 0-100 percentage).
_PROPORTION_INDICATORS = frozenset({"environment.greenspace.access_pct"})


class FoeGreenSpaceLoader(LoaderAdapter):
    source_id = SOURCE_ID

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        client: FoeGreenSpaceClient | None = None,
    ) -> None:
        super().__init__(engine)
        self._client = client or FoeGreenSpaceClient()

    async def load(self, run_id: str | None = None) -> LoaderResult:
        content = await self._client.fetch_workbook()
        values = list(
            self._extract(
                self._client.read_sheet(content, LSOA_SHEET),
                code_col="LSOA_Code",
                place_type="lsoa21",
                metrics=_COMMON_METRICS,
            )
        )
        values += list(
            self._extract(
                self._client.read_sheet(content, LA_SHEET),
                code_col="LA_Code",
                place_type="ltla24",
                metrics={**_COMMON_METRICS, **_LA_ONLY_METRICS},
            )
        )
        written, skipped = await self._upsert_values(values)
        notes = f"{skipped} values skipped (place not in spine)" if skipped else None
        return LoaderResult(rows_written=written, notes=notes)

    @staticmethod
    def _extract(
        rows: Iterable[dict[str, Any]],
        *,
        code_col: str,
        place_type: str,
        metrics: dict[str, str],
    ) -> Iterable[tuple[str, str, float]]:
        """Yield (place_id, indicator_key, value) for each populated metric.
        Percentage columns are converted to a 0-1 proportion."""
        for row in rows:
            code = row.get(code_col)
            if not code:
                continue
            place_id = f"{place_type}:{str(code).strip()}"
            for column, indicator_key in metrics.items():
                value = _coerce_float(row.get(column))
                if value is None:
                    continue
                if indicator_key in _PROPORTION_INDICATORS:
                    value = value / 100.0
                yield (place_id, indicator_key, value)

    async def _upsert_values(self, values: list[tuple[str, str, float]]) -> tuple[int, int]:
        if not values:
            return (0, 0)
        candidate_ids = {place_id for place_id, _, _ in values}
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT id FROM geography.place WHERE id = ANY(:ids)"),
                    {"ids": list(candidate_ids)},
                )
            ).all()
        known = {r.id for r in rows}

        retrieved_at = datetime.now(tz=UTC)
        params = [
            {
                "place_id": place_id,
                "indicator_key": indicator_key,
                "period": PERIOD,
                "value": value,
                "source_id": self.source_id,
                "retrieved_at": retrieved_at,
            }
            for place_id, indicator_key, value in values
            if place_id in known
        ]
        skipped = len(values) - len(params)
        if not params:
            return (0, skipped)

        upsert_sql = text(
            "INSERT INTO data.indicator_value "
            "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) "
            "VALUES (:place_id, :indicator_key, :period, :value, :source_id, "
            "        :retrieved_at, '[]'::jsonb) "
            "ON CONFLICT (place_id, indicator_key, period) "
            "DO UPDATE SET value = EXCLUDED.value, "
            "              retrieved_at = EXCLUDED.retrieved_at, "
            "              source_id = EXCLUDED.source_id"
        )
        async with self._engine.begin() as conn:
            for i in range(0, len(params), UPSERT_CHUNK):
                await conn.execute(upsert_sql, params[i : i + UPSERT_CHUNK])
        return (len(params), skipped)


def _coerce_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(value):
        return None
    return value

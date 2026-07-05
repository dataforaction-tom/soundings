"""CompaniesHouseLoader — writes per-LTLA company-count indicators from
the monthly Companies House Free Company Data Product.

Aggregates-only: we stream the bulk CSV, accumulate counts keyed by
normalised postcode (bounded memory — the distinct-postcode set, not the
~5M company rows), resolve those postcodes to LTLAs, roll up, and UPSERT
the aggregates into `data.indicator_value`. No per-company rows are
stored — see `docs/plans/2026-06-30-companies-house-loader-plan.md`.

Indicators written per LTLA:
- economy.active_companies_count
- economy.active_companies_per_1000  (joins latest population.total)
- economy.new_incorporations_12m
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.base import LoaderAdapter, LoaderResult
from soundings.adapters.companies_house.client import CompaniesHouseBulkClient
from soundings.adapters.postcodes_io.adapter import PostcodesIoAdapter, _normalise_postcode
from soundings.adapters.postcodes_io.resolver import resolve_postcodes_to_ltlas

SOURCE_ID = "companies_house"
POSTCODES_IO_TTL_HOURS = 720  # 30 days, matches sources.yaml
INCORPORATION_WINDOW_DAYS = 365


@dataclass
class _Agg:
    count: int = 0
    incorporations_12m: int = 0


class CompaniesHouseLoader(LoaderAdapter):
    source_id = SOURCE_ID

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        bulk_client: CompaniesHouseBulkClient | None = None,
        postcodes_io: PostcodesIoAdapter | None = None,
        as_of: date | None = None,
    ) -> None:
        super().__init__(engine)
        self._as_of = as_of
        # The default bulk client is built lazily in load(), once as_of is
        # resolved — building it here with the (possibly None) __init__ as_of
        # left the daemon path unable to resolve download URLs.
        self._bulk_client = bulk_client
        self._postcodes_io = postcodes_io or PostcodesIoAdapter(
            engine, ttl=timedelta(hours=POSTCODES_IO_TTL_HOURS)
        )

    async def load(self, run_id: str | None = None) -> LoaderResult:
        retrieved_at = datetime.now(tz=UTC)
        as_of = self._as_of or retrieved_at.date()
        client = self._bulk_client or CompaniesHouseBulkClient(as_of=as_of)

        # Pass 1: stream + accumulate per normalised postcode (bounded memory).
        postcode_aggs = await self._accumulate(client.iter_active_companies(), as_of=as_of)

        # Pass 2: resolve the distinct postcode set to LTLAs (cache-first).
        resolved = await resolve_postcodes_to_ltlas(self._postcodes_io, list(postcode_aggs.keys()))

        # Pass 3: roll up to LTLA + UPSERT indicator values.
        ltla_aggs = self._rollup_to_ltla(postcode_aggs, resolved)
        period = retrieved_at.strftime("%Y-%m")
        missing_pop = await self._upsert_indicators(ltla_aggs, period, retrieved_at)

        unresolved = sum(1 for norm in postcode_aggs if resolved.get(norm) is None)
        note_pieces: list[str] = []
        if unresolved:
            note_pieces.append(f"{unresolved} postcodes unresolved — excluded from LTLA counts")
        if missing_pop:
            note_pieces.append(f"{missing_pop} LTLAs without population.total — per_1000 skipped")
        notes = "; ".join(note_pieces) if note_pieces else None
        return LoaderResult(rows_written=len(ltla_aggs), notes=notes)

    # --- pure aggregation helpers ----------------------------------------

    @staticmethod
    async def _accumulate(
        companies: AsyncIterator[dict[str, Any]],
        *,
        as_of: date,
    ) -> dict[str, _Agg]:
        """Accumulate counts keyed by normalised postcode. Companies with no
        postcode are skipped (they can't be placed in an LTLA)."""
        cutoff = as_of - timedelta(days=INCORPORATION_WINDOW_DAYS)
        aggs: dict[str, _Agg] = {}
        async for company in companies:
            postcode = (company.get("postcode") or "").strip()
            if not postcode:
                continue
            norm = _normalise_postcode(postcode)
            agg = aggs.get(norm)
            if agg is None:
                agg = _Agg()
                aggs[norm] = agg
            agg.count += 1
            if _incorporated_within(company.get("incorporation_date"), cutoff):
                agg.incorporations_12m += 1
        return aggs

    @staticmethod
    def _rollup_to_ltla(
        postcode_aggs: dict[str, _Agg],
        resolved: dict[str, str | None],
    ) -> dict[str, _Agg]:
        """Sum per-postcode aggregates into per-LTLA aggregates, dropping
        postcodes that didn't resolve to an LTLA."""
        out: dict[str, _Agg] = {}
        for norm, agg in postcode_aggs.items():
            ltla = resolved.get(norm)
            if ltla is None:
                continue
            target = out.get(ltla)
            if target is None:
                target = _Agg()
                out[ltla] = target
            target.count += agg.count
            target.incorporations_12m += agg.incorporations_12m
        return out

    # --- indicator UPSERT -------------------------------------------------

    async def _upsert_indicators(
        self,
        ltla_aggs: dict[str, _Agg],
        period: str,
        retrieved_at: datetime,
    ) -> int:
        """UPSERT the three economy indicators. Returns the number of LTLAs
        that have a count but no population.total (per_1000 skipped)."""
        if not ltla_aggs:
            return 0

        count_rows = [
            {
                "place_id": place_id,
                "indicator_key": "economy.active_companies_count",
                "period": period,
                "value": float(agg.count),
                "source_id": self.source_id,
                "retrieved_at": retrieved_at,
            }
            for place_id, agg in ltla_aggs.items()
        ]
        incorp_rows = [
            {
                "place_id": place_id,
                "indicator_key": "economy.new_incorporations_12m",
                "period": period,
                "value": float(agg.incorporations_12m),
                "source_id": self.source_id,
                "retrieved_at": retrieved_at,
            }
            for place_id, agg in ltla_aggs.items()
        ]

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
            await conn.execute(upsert_sql, count_rows)
            await conn.execute(upsert_sql, incorp_rows)

            # per_1000 joins the latest population.total for each place.
            await conn.execute(
                text(
                    "WITH populations AS ("
                    "  SELECT DISTINCT ON (place_id) place_id, value AS pop "
                    "  FROM data.indicator_value "
                    "  WHERE indicator_key = 'population.total' AND value IS NOT NULL "
                    "  ORDER BY place_id, period DESC"
                    ") "
                    "INSERT INTO data.indicator_value "
                    "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) "
                    "SELECT c.place_id, 'economy.active_companies_per_1000', :period, "
                    "       c.cnt::numeric / p.pop * 1000.0, :sid, :now, '[]'::jsonb "
                    "FROM (SELECT place_id, value AS cnt FROM data.indicator_value "
                    "      WHERE indicator_key = 'economy.active_companies_count' "
                    "        AND period = :period AND source_id = :sid) c "
                    "INNER JOIN populations p ON p.place_id = c.place_id "
                    "WHERE p.pop > 0 "
                    "ON CONFLICT (place_id, indicator_key, period) "
                    "DO UPDATE SET value = EXCLUDED.value, "
                    "              retrieved_at = EXCLUDED.retrieved_at, "
                    "              source_id = EXCLUDED.source_id"
                ),
                {"period": period, "sid": self.source_id, "now": retrieved_at},
            )

            missing_pop_row = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) AS n FROM data.indicator_value c "
                        "WHERE c.indicator_key = 'economy.active_companies_count' "
                        "  AND c.period = :period AND c.source_id = :sid "
                        "  AND NOT EXISTS ("
                        "    SELECT 1 FROM data.indicator_value p "
                        "    WHERE p.place_id = c.place_id "
                        "      AND p.indicator_key = 'population.total')"
                    ),
                    {"period": period, "sid": self.source_id},
                )
            ).first()
        return int(missing_pop_row.n) if missing_pop_row else 0


def _incorporated_within(raw: str | None, cutoff: date) -> bool:
    """True if the DD/MM/YYYY incorporation date is on or after cutoff."""
    if not raw:
        return False
    try:
        parsed = datetime.strptime(raw, "%d/%m/%Y").date()
    except ValueError:
        return False
    return parsed >= cutoff

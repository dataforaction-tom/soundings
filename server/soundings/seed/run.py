"""CLI: `python -m soundings.seed.run --full | --light`.

Wraps the ons.geography loaders (places, hierarchy, geometries, code change)
and writes a `data.loader_run` row per loader. Intended to be run inside the
docker compose `server` container via `make seed` / `make seed-light`.

`--light` skips the heaviest layers (LSOA + MSOA) so a Mac mini dev box can
get a usable spine in ~5 minutes for testing.
"""

import argparse
import asyncio
import sys
import uuid
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.base import LoaderResult
from soundings.adapters.ons_geography.chains import ALL_CHAINS
from soundings.adapters.ons_geography.code_change_loader import (
    OnsGeographyCodeChangeLoader,
)
from soundings.adapters.ons_geography.endpoints import BOUNDARY_LAYERS
from soundings.adapters.ons_geography.geometries_loader import (
    OnsGeographyGeometriesLoader,
)
from soundings.adapters.ons_geography.hierarchy_loader import (
    OnsGeographyHierarchyLoader,
)
from soundings.adapters.mhclg_imd2025.aggregation import aggregate_imd_to_ltla
from soundings.adapters.mhclg_imd2025.loader import MhclgImd2025Loader
from soundings.adapters.ons_census2021.loader import OnsCensus2021Loader
from soundings.adapters.ons_geography.places_loader import OnsGeographyPlacesLoader
from soundings.adapters.ons_mid_year_estimates.loader import OnsMidYearEstimatesLoader
from soundings.db.engine import get_engine

LIGHT_LAYERS = {"ltla24", "utla24", "region", "country", "westminster_constituency_24", "ward24"}


async def _run_loader(
    engine: AsyncEngine,
    source_id: str,
    name: str,
    coro: Coroutine[Any, Any, LoaderResult],
) -> LoaderResult:
    run_id = uuid.uuid4()
    started = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO data.loader_run (id, source_id, started_at, status) "
                "VALUES (:id, :sid, :st, 'running')"
            ),
            {"id": run_id, "sid": source_id, "st": started},
        )
    try:
        result: LoaderResult = await coro
        finished = datetime.now(tz=UTC)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE data.loader_run "
                    "SET status='ok', finished_at=:f, rows_written=:r, notes=:n "
                    "WHERE id=:id"
                ),
                {
                    "f": finished,
                    "r": result.rows_written,
                    "n": result.notes,
                    "id": run_id,
                },
            )
        print(f"[seed] {name}: {result.rows_written} rows ({result.notes or 'ok'})")
        return result
    except Exception as exc:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE data.loader_run "
                    "SET status='failed', finished_at=:f, notes=:n WHERE id=:id"
                ),
                {
                    "f": datetime.now(tz=UTC),
                    "n": f"{exc.__class__.__name__}: {exc}",
                    "id": run_id,
                },
            )
        raise


async def _seed(*, full: bool) -> None:
    engine = get_engine()

    layers = (
        BOUNDARY_LAYERS if full else {k: v for k, v in BOUNDARY_LAYERS.items() if k in LIGHT_LAYERS}
    )

    places = OnsGeographyPlacesLoader(engine, layers=layers)
    await _run_loader(engine, "ons.geography", "places", places.load())

    hierarchy = OnsGeographyHierarchyLoader(engine, chains=ALL_CHAINS)
    await _run_loader(engine, "ons.geography", "hierarchy", hierarchy.load())

    geoms = OnsGeographyGeometriesLoader(engine, layers=layers)
    await _run_loader(engine, "ons.geography", "geometries", geoms.load())

    chd = OnsGeographyCodeChangeLoader(engine)
    await _run_loader(engine, "ons.geography", "code_change", chd.load())

    # Indicator data — Phase 1 sources. `--light` filters to the dev LTLA
    # so a fresh box doesn't burn through Nomis rate limits.
    light_filter = ["ltla24:E06000004"] if not full else None
    mye = OnsMidYearEstimatesLoader(engine, place_filter=light_filter)
    await _run_loader(engine, "ons.mid_year_estimates", "mye", mye.load())

    census = OnsCensus2021Loader(engine, place_filter=light_filter)
    await _run_loader(engine, "ons.census2021", "census", census.load())

    # IMD must run after MYE: the LSOA→LTLA aggregation is population-weighted
    # using mid-year estimate values.
    imd = MhclgImd2025Loader(engine)
    await _run_loader(engine, "mhclg.imd2025", "imd", imd.load())
    aggregated = await aggregate_imd_to_ltla(engine)
    print(f"[seed] imd_aggregation: {aggregated} LTLA rows")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="soundings-seed")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--full", action="store_true")
    mode.add_argument("--light", action="store_true")
    args = parser.parse_args(argv)
    asyncio.run(_seed(full=args.full))
    return 0


if __name__ == "__main__":
    sys.exit(main())

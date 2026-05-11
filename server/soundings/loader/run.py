"""CLI: `python -m soundings.loader.run [--once <source_id>]`.

APScheduler daemon that fires each catalogue.source's loader on its
refresh_cadence. The same image as `server` runs this with a different
ENTRYPOINT (Docker Compose `loader` service).
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.mhclg_imd2025.aggregation import aggregate_imd_to_ltla
from soundings.adapters.mhclg_imd2025.loader import MhclgImd2019Loader, MhclgImd2025Loader
from soundings.adapters.ons_census2021.loader import OnsCensus2021Loader
from soundings.adapters.ons_geography.chains import ALL_CHAINS
from soundings.adapters.ons_geography.code_change_loader import (
    OnsGeographyCodeChangeLoader,
)
from soundings.adapters.ons_geography.geometries_loader import (
    OnsGeographyGeometriesLoader,
)
from soundings.adapters.ons_geography.hierarchy_loader import (
    OnsGeographyHierarchyLoader,
)
from soundings.adapters.ons_geography.places_loader import OnsGeographyPlacesLoader
from soundings.adapters.ons_mid_year_estimates.loader import OnsMidYearEstimatesLoader
from soundings.capture.retention import delete_old_raw_records
from soundings.db.engine import get_engine

LoaderCallable = Callable[[], Awaitable[None]]


def build_source_registry(engine: AsyncEngine) -> dict[str, LoaderCallable]:
    """Map source_id → idempotent loader coroutine factory."""

    async def _geography() -> None:
        await OnsGeographyPlacesLoader(engine).load()
        await OnsGeographyHierarchyLoader(engine, chains=ALL_CHAINS).load()
        await OnsGeographyGeometriesLoader(engine).load()
        await OnsGeographyCodeChangeLoader(engine).load()

    async def _mye() -> None:
        await OnsMidYearEstimatesLoader(engine).load()

    async def _census() -> None:
        await OnsCensus2021Loader(engine).load()

    async def _imd2025() -> None:
        await MhclgImd2025Loader(engine).load()
        await aggregate_imd_to_ltla(engine, source_id="mhclg.imd2025")

    async def _imd2019() -> None:
        await MhclgImd2019Loader(engine).load()
        await aggregate_imd_to_ltla(engine, source_id="mhclg.imd2019")

    return {
        "ons.geography": _geography,
        "ons.mid_year_estimates": _mye,
        "ons.census2021": _census,
        "mhclg.imd2025": _imd2025,
        "mhclg.imd2019": _imd2019,
    }


async def build_scheduler(
    engine: AsyncEngine, registry: dict[str, LoaderCallable]
) -> AsyncIOScheduler:
    sched = AsyncIOScheduler()
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id, refresh_cadence FROM catalogue.source WHERE mode = 'loader'")
            )
        ).all()
    for row in rows:
        loader = registry.get(row.id)
        if loader is None or not row.refresh_cadence:
            continue
        trigger = CronTrigger.from_crontab(row.refresh_cadence)
        sched.add_job(loader, trigger=trigger, id=row.id, name=row.id)

    # Cross-source retention: daily at 04:00 UTC, deletes corpus.raw_record
    # rows older than 30 days. Not in catalogue.source (it's an internal job).
    async def _retention() -> None:
        await delete_old_raw_records(engine)

    sched.add_job(
        _retention,
        trigger=CronTrigger.from_crontab("0 4 * * *"),
        id="corpus.retention",
        name="corpus.retention",
    )
    return sched


async def _run_forever() -> None:
    engine = get_engine()
    registry = build_source_registry(engine)
    sched = await build_scheduler(engine, registry)
    sched.start()
    try:
        # Sleep until cancelled — APScheduler runs in the same event loop.
        while True:
            await asyncio.sleep(3600)
    finally:
        sched.shutdown(wait=False)


async def _run_once(source_id: str) -> int:
    engine = get_engine()
    registry = build_source_registry(engine)
    loader = registry.get(source_id)
    if loader is None:
        print(f"[loader] unknown source_id: {source_id}", file=sys.stderr)
        return 1
    print(f"[loader] running {source_id} once")
    await loader()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="soundings-loader")
    parser.add_argument("--once", metavar="SOURCE_ID")
    args = parser.parse_args(argv)
    if args.once:
        return asyncio.run(_run_once(args.once))
    asyncio.run(_run_forever())
    return 0


if __name__ == "__main__":
    sys.exit(main())

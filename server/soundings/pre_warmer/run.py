"""CLI: `python -m soundings.pre_warmer.run [--once <source_id>...]`.

APScheduler daemon that calls `pre_warm_for_places(<all LTLAs>)` on
every registered passthrough adapter on its `refresh_cadence` cron.
The pre_warmer keeps user-facing reads on a warm cache for aggregate
indicators that would otherwise be expensive to compute live
(`civil_society.active_charities_count`, grant sums, etc.).

Same image as the `server` / `loader` Docker Compose services with a
different entrypoint.
"""

import argparse
import asyncio
import logging
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.db.engine import get_engine
from soundings.orchestration.registry import AdapterRegistry

_log = logging.getLogger("soundings.pre_warmer")


async def fetch_place_ids_for_warming(engine: AsyncEngine) -> list[str]:
    """All LTLA place ids. The cache-warming domain for v1 — passthrough
    aggregates publish at LTLA granularity, so that's what we pre-warm."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id FROM geography.place WHERE type = 'ltla24' ORDER BY id")
            )
        ).all()
    return [r.id for r in rows]


async def _warm_one(adapter: PassthroughAdapter, place_ids: list[str]) -> None:
    _log.info("pre-warming source_id=%s for %d places", adapter.source_id, len(place_ids))
    await adapter.safe_pre_warm(place_ids)


async def run_pre_warm_once(
    engine: AsyncEngine,
    registry: AdapterRegistry,
    source_ids: list[str],
) -> int:
    """Fire `pre_warm_for_places(all ltlas)` once for each requested
    source_id. Returns 0 on success (including soft-fail from
    misbehaving adapters); nonzero if a requested source_id isn't
    registered."""
    place_ids = await fetch_place_ids_for_warming(engine)
    rc = 0
    for source_id in source_ids:
        try:
            adapter = registry.adapter_for_source(source_id)
        except Exception:
            _log.error("pre_warm: unknown source_id=%s", source_id)
            rc = 2
            continue
        await _warm_one(adapter, place_ids)
    return rc


def _build_scheduler(
    engine: AsyncEngine,
    registry: AdapterRegistry,
    source_id_to_cron: dict[str, str],
) -> AsyncIOScheduler:
    sched = AsyncIOScheduler()
    for source_id, cron in source_id_to_cron.items():

        async def _job(sid: str = source_id) -> None:
            await run_pre_warm_once(engine, registry, [sid])

        sched.add_job(
            _job,
            trigger=CronTrigger.from_crontab(cron),
            id=f"pre_warm.{source_id}",
            name=f"pre_warm.{source_id}",
        )
    return sched


async def _load_cron_per_source(engine: AsyncEngine) -> dict[str, str]:
    """For every passthrough source with a refresh_cadence, fold it into a
    cron-trigger config. The pre_warmer fires the warm pass at the same
    cadence the source itself refreshes — the cache TTL is matched."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, refresh_cadence FROM catalogue.source "
                    "WHERE mode = 'passthrough' AND refresh_cadence IS NOT NULL"
                )
            )
        ).all()
    return {r.id: r.refresh_cadence for r in rows}


async def _run_forever() -> None:
    engine = get_engine()
    # Adapters are registered in soundings.app.lifespan; for a standalone
    # pre_warmer process we build the registry the same way. Block A onwards
    # extends this list as new passthrough adapters land.
    from soundings.app import build_adapter_registry  # local import: avoids cyc

    registry = build_adapter_registry(engine)
    sources = await _load_cron_per_source(engine)
    sched = _build_scheduler(engine, registry, sources)
    sched.start()
    _log.info(
        "pre_warmer running; %d sources scheduled: %s",
        len(sources),
        list(sources),
    )
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        sched.shutdown(wait=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="soundings-pre-warmer")
    parser.add_argument(
        "--once",
        nargs="+",
        metavar="SOURCE_ID",
        help="Run the warmer once for the given source_id(s) and exit.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.once:
        from soundings.app import build_adapter_registry

        engine = get_engine()
        registry = build_adapter_registry(engine)
        return asyncio.run(run_pre_warm_once(engine, registry, args.once))
    asyncio.run(_run_forever())
    return 0


if __name__ == "__main__":
    sys.exit(main())

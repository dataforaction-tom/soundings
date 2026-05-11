"""Replay pending sanitisations.

Two callers:

1. **App startup** (lifespan hook). After a process crash mid-sanitise,
   `corpus.question_record` rows may sit at `review_status='pending'`
   despite the raw_record still being there. We sweep those at boot so
   the corpus self-heals without manual intervention.

2. **Manual CLI** — `python -m soundings.capture.replay [--since YYYY-MM-DD]`.
   Useful when the sanitisation rules version bumps and we want to
   re-run the new pipeline against the 30-day raw window.

Concurrency is capped via `asyncio.Semaphore` so a backlog doesn't
swamp spaCy on a Mac mini's ~400MB server budget.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


class _Sanitiser(Protocol):
    async def sanitise(self, record_id: UUID) -> None: ...


async def _select_pending_ids(engine: AsyncEngine, since: datetime | None) -> list[UUID]:
    """Pending rows that still have a matching raw_record."""
    sql = (
        "SELECT q.id FROM corpus.question_record q "
        "JOIN corpus.raw_record r ON r.id = q.id "
        "WHERE q.review_status = 'pending'"
    )
    params: dict[str, datetime] = {}
    if since is not None:
        sql += " AND q.timestamp >= :since"
        params["since"] = since
    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql), params)).all()
    return [row.id for row in rows]


async def replay_pending(
    engine: AsyncEngine,
    worker: _Sanitiser,
    *,
    max_concurrent: int = 4,
    since: datetime | None = None,
) -> int:
    """Sanitise every pending record (optionally since a cutoff).

    Returns the count of records processed. Each record runs through the
    worker independently; one record's failure is the worker's problem
    (it'll fire the alert callable and leave the row at pending), not
    this caller's.
    """
    ids = await _select_pending_ids(engine, since)
    if not ids:
        return 0

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _one(record_id: UUID) -> None:
        async with semaphore:
            await worker.sanitise(record_id)

    await asyncio.gather(*[_one(rid) for rid in ids])
    return len(ids)


def _parse_since(arg: str | None) -> datetime | None:
    if arg is None:
        return None
    return datetime.fromisoformat(arg).astimezone()


async def _cli_main(args: argparse.Namespace) -> int:
    # Local imports to keep the module importable without a running app.
    from soundings.capture.sanitisation.config import load_sanitisation_config
    from soundings.capture.sanitisation.direct_identifiers import (
        StripDirectIdentifiers,
    )
    from soundings.capture.sanitisation.normalise import (
        NormaliseAskerPurpose,
        ValidateConsentLevel,
    )
    from soundings.capture.sanitisation.pipeline import SanitisationPipeline
    from soundings.capture.sanitiser_worker import SanitiserWorker
    from soundings.db.engine import get_engine

    engine = get_engine()
    config = load_sanitisation_config()
    pipeline = SanitisationPipeline(
        rules=[
            StripDirectIdentifiers(),
            NormaliseAskerPurpose(),
            ValidateConsentLevel(),
        ]
    )
    worker = SanitiserWorker(engine, pipeline, config)

    count = await replay_pending(
        engine,
        worker,
        max_concurrent=args.max_concurrent,
        since=_parse_since(args.since),
    )
    logger.info("replayed %s pending records", count)
    print(f"[replay] processed {count} records")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="soundings-replay")
    parser.add_argument(
        "--since",
        metavar="ISO_DATE",
        help="Only replay records newer than this ISO date (e.g. 2026-05-01).",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=4,
        help="Concurrency cap on the sanitiser (default 4).",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_cli_main(args))


if __name__ == "__main__":
    sys.exit(main())

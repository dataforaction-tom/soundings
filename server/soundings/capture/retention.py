"""30-day retention for corpus.raw_record.

Daily APScheduler job deletes raw_record rows older than 30 days.
question_record rows are never deleted — those carry the sanitised
publishable payload.

Permanent-orphan stub note (ADR-0003): if a record's sanitiser failed
and we delete its raw_record here, the corresponding question_record
stays at review_status='pending' forever. That's acceptable because
the publication query filters those rows out; a follow-up cron in
Phase 3 hard-deletes pending stubs older than 60 days.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.alerts import send_alert

logger = logging.getLogger(__name__)

RETENTION_WINDOW = timedelta(days=30)


async def delete_old_raw_records(
    engine: AsyncEngine,
    *,
    window: timedelta = RETENTION_WINDOW,
) -> int:
    """Returns rows deleted. Logs + alerts on failure but re-raises so the
    cron's last_run state reflects the error."""
    cutoff = datetime.now(tz=UTC) - window
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM corpus.raw_record WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
        count = result.rowcount or 0
        logger.info("retention deleted %s raw_record rows older than %s", count, cutoff)
        return count
    except Exception as exc:
        logger.exception("raw_record retention failed")
        send_alert(
            "Raw-record retention failed",
            f"Cutoff {cutoff.isoformat()} — exception {exc!r}",
            source="retention",
        )
        raise

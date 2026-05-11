"""FullConsentRateLimiter — silent downgrade after N full-consent records.

Spec §8.3: capture under full consent is rate-limited per session (60
records/hour by default). On exceeding the threshold, further records
in the same session land at `minimal` even if the cookie still says
`full`. The asker sees no error.

The limiter counts rows in `corpus.question_record` directly. A
follow-up index on `(session_id, capture_level, timestamp)` will be
needed at scale; in v1 the table is small enough that a scan is fine.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class FullConsentRateLimiter:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        threshold: int = 60,
        window: timedelta = timedelta(hours=1),
    ) -> None:
        self._engine = engine
        self._threshold = threshold
        self._window = window

    async def should_downgrade(self, session_id: UUID) -> bool:
        cutoff = datetime.now(tz=UTC) - self._window
        async with self._engine.connect() as conn:
            count = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM corpus.question_record "
                        "WHERE session_id = :sid "
                        "AND capture_level = 'full' "
                        "AND timestamp >= :cutoff"
                    ),
                    {"sid": session_id, "cutoff": cutoff},
                )
            ).scalar_one()
        return bool(count >= self._threshold)

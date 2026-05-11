"""select_publishable — pull rows ready for monthly publication.

A row is publishable when:
    consent_version IS NOT NULL
    AND capture_level IN ('full', 'minimal')   -- 'none' never reaches here
    AND review_status = 'cleared'              -- not pending, flagged, released
    AND timestamp < :period_end                -- typically start of the month

Result ordering is deterministic (`timestamp` ASC then `id`) so two
runs over the same DB produce byte-identical archives.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class PublishableRecord:
    id: UUID
    timestamp: datetime
    session_id: UUID
    consent_version: str
    capture_level: str
    tool_called: str
    tool_inputs_redacted: dict[str, Any]
    geography_referenced: list[dict[str, str]] | dict[str, Any]
    indicators_returned: list[str]
    sources_used: list[str]
    result_status: str
    error_class: str | None
    asker_sector: str | None
    asker_purpose: str | None
    marked_useful: bool | None
    natural_language_question: str | None
    sanitisation_rules_version: str | None


async def select_publishable(engine: AsyncEngine, period_end: datetime) -> list[PublishableRecord]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, timestamp, session_id, consent_version, "
                    "capture_level, tool_called, tool_inputs_redacted, "
                    "geography_referenced, indicators_returned, sources_used, "
                    "result_status, error_class, asker_sector, asker_purpose, "
                    "marked_useful, natural_language_question, "
                    "sanitisation_rules_version "
                    "FROM corpus.question_record "
                    "WHERE consent_version IS NOT NULL "
                    "AND capture_level IN ('full','minimal') "
                    "AND review_status = 'cleared' "
                    "AND timestamp < :period_end "
                    "ORDER BY timestamp ASC, id ASC"
                ),
                {"period_end": period_end},
            )
        ).all()
    return [
        PublishableRecord(
            id=row.id,
            timestamp=row.timestamp,
            session_id=row.session_id,
            consent_version=row.consent_version,
            capture_level=row.capture_level,
            tool_called=row.tool_called,
            tool_inputs_redacted=row.tool_inputs_redacted,
            geography_referenced=row.geography_referenced,
            indicators_returned=list(row.indicators_returned or []),
            sources_used=list(row.sources_used or []),
            result_status=row.result_status,
            error_class=row.error_class,
            asker_sector=row.asker_sector,
            asker_purpose=row.asker_purpose,
            marked_useful=row.marked_useful,
            natural_language_question=row.natural_language_question,
            sanitisation_rules_version=row.sanitisation_rules_version,
        )
        for row in rows
    ]

"""RawRecordWriter — synchronous two-row write into corpus.{question,raw}.

Both rows land in the same DB transaction as the tool's response. The
schema FK `raw_record.id → question_record.id` (set in Phase 0 migration
0004) is satisfied by writing the question_record stub first and the
raw_record second under the same UUID.

The sanitiser (Task 16) later picks up the raw_record and updates the
matching question_record with sanitised fields. See ADR-0003 (Task 18)
for why the FK runs in that direction despite the design saying
"raw first".

If `consent_level == "none"`, this writer is a no-op.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.capture.context import CaptureContext


class RawRecordWriter:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def write(self, ctx: CaptureContext) -> uuid.UUID | None:
        """Returns the new record_id, or None if the write was skipped."""
        if ctx.consent_level == "none" or ctx.session_id is None:
            return None

        record_id = uuid.uuid4()
        timestamp = datetime.now(tz=UTC)

        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO corpus.question_record ("
                    "id, timestamp, session_id, consent_version, capture_level, "
                    "tool_called, tool_inputs_redacted, geography_referenced, "
                    "indicators_returned, sources_used, result_status, error_class, "
                    "gap_signals"
                    ") VALUES ("
                    ":id, :ts, :sid, :cv, :cl, "
                    ":tool, '{}'::jsonb, '{}'::jsonb, "
                    ":ind, :srcs, :status, :err, "
                    "ARRAY[]::varchar[]"
                    ")"
                ),
                {
                    "id": record_id,
                    "ts": timestamp,
                    "sid": ctx.session_id,
                    "cv": ctx.consent_version,
                    "cl": ctx.consent_level,
                    "tool": ctx.tool_called,
                    "ind": ctx.indicators_returned,
                    "srcs": ctx.sources_used,
                    "status": ctx.result_status,
                    "err": ctx.error_class,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO corpus.raw_record (id, raw_payload, created_at) "
                    "VALUES (:id, CAST(:payload AS JSONB), :ts)"
                ),
                {
                    "id": record_id,
                    "ts": timestamp,
                    "payload": _build_raw_payload(ctx),
                },
            )
        return record_id


def _build_raw_payload(ctx: CaptureContext) -> str:
    import json

    return json.dumps(
        {
            "capture_level": ctx.consent_level,
            "tool_inputs": ctx.tool_inputs,
            "natural_language_question": ctx.natural_language_question,
            "asker_sector": ctx.asker_sector,
            "asker_purpose": ctx.asker_purpose,
            "geography_referenced": ctx.geography_referenced,
        }
    )

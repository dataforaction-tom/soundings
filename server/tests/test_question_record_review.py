"""Migration 0005 verification: review_status defaults + new column present."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def test_review_status_defaults_to_pending() -> None:
    engine = get_engine()
    record_id = uuid.uuid4()
    session_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM corpus.raw_record"))
        await conn.execute(text("DELETE FROM corpus.question_record"))
        await conn.execute(
            text(
                "INSERT INTO corpus.question_record ("
                "id, timestamp, session_id, consent_version, capture_level, "
                "tool_called, tool_inputs_redacted, geography_referenced, "
                "indicators_returned, sources_used, result_status, gap_signals"
                ") VALUES ("
                ":id, :ts, :sid, 'v1.0', 'minimal', 'find_place', "
                "'{}'::jsonb, '{}'::jsonb, ARRAY[]::varchar[], ARRAY[]::varchar[], "
                "'ok', ARRAY[]::varchar[]"
                ")"
            ),
            {"id": record_id, "ts": datetime.now(tz=UTC), "sid": session_id},
        )

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT review_status, sanitisation_rules_version "
                    "FROM corpus.question_record WHERE id = :id"
                ),
                {"id": record_id},
            )
        ).first()

    assert row is not None
    assert row.review_status == "pending"
    assert row.sanitisation_rules_version is None

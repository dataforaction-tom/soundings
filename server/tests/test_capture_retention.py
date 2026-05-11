"""Integration tests for the raw_record 30-day retention cron."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from soundings.capture.retention import delete_old_raw_records
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_pair(record_id: uuid.UUID, timestamp: datetime) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO corpus.question_record ("
                "id, timestamp, session_id, consent_version, capture_level, "
                "tool_called, tool_inputs_redacted, geography_referenced, "
                "indicators_returned, sources_used, result_status, gap_signals, "
                "review_status"
                ") VALUES ("
                ":id, :ts, :sid, 'v1.0', 'minimal', 'find_place', "
                "'{}'::jsonb, '{}'::jsonb, ARRAY[]::varchar[], ARRAY[]::varchar[], "
                "'ok', ARRAY[]::varchar[], 'cleared'"
                ")"
            ),
            {"id": record_id, "ts": timestamp, "sid": uuid.uuid4()},
        )
        await conn.execute(
            text(
                "INSERT INTO corpus.raw_record (id, raw_payload, created_at) "
                "VALUES (:id, '{}'::jsonb, :ts)"
            ),
            {"id": record_id, "ts": timestamp},
        )


async def _clean() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM corpus.raw_record"))
        await conn.execute(text("DELETE FROM corpus.question_record"))


async def test_retention_deletes_old_raw_keeps_recent() -> None:
    await _clean()
    fresh_id = uuid.uuid4()
    old_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    await _seed_pair(fresh_id, now)
    await _seed_pair(old_id, now - timedelta(days=31))

    deleted = await delete_old_raw_records(get_engine())
    assert deleted == 1

    engine = get_engine()
    async with engine.connect() as conn:
        raw_ids = {
            row.id for row in (await conn.execute(text("SELECT id FROM corpus.raw_record"))).all()
        }
        question_ids = {
            row.id
            for row in (await conn.execute(text("SELECT id FROM corpus.question_record"))).all()
        }
    assert raw_ids == {fresh_id}
    # question_record rows are NEVER deleted by retention.
    assert question_ids == {fresh_id, old_id}


async def test_retention_with_custom_window() -> None:
    await _clean()
    rid = uuid.uuid4()
    await _seed_pair(rid, datetime.now(tz=UTC) - timedelta(hours=2))

    # 1-hour retention window — the 2-hour-old row gets deleted.
    deleted = await delete_old_raw_records(get_engine(), window=timedelta(hours=1))
    assert deleted == 1

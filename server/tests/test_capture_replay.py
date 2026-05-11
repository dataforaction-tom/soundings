"""Integration tests for replay_pending."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from soundings.capture.replay import replay_pending
from soundings.capture.sanitisation.config import load_sanitisation_config
from soundings.capture.sanitisation.direct_identifiers import StripDirectIdentifiers
from soundings.capture.sanitisation.pipeline import SanitisationPipeline
from soundings.capture.sanitiser_worker import SanitiserWorker
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration

CONFIG = load_sanitisation_config()


async def _seed_pending_records(count: int, *, timestamp: datetime) -> list[uuid.UUID]:
    engine = get_engine()
    ids: list[uuid.UUID] = []
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM corpus.raw_record"))
        await conn.execute(text("DELETE FROM corpus.question_record"))
        for i in range(count):
            rid = uuid.uuid4()
            ids.append(rid)
            await conn.execute(
                text(
                    "INSERT INTO corpus.question_record ("
                    "id, timestamp, session_id, consent_version, capture_level, "
                    "tool_called, tool_inputs_redacted, geography_referenced, "
                    "indicators_returned, sources_used, result_status, gap_signals, "
                    "review_status"
                    ") VALUES ("
                    ":id, :ts, :sid, 'v1.0', 'full', 'find_place', "
                    "'{}'::jsonb, '{}'::jsonb, ARRAY[]::varchar[], ARRAY[]::varchar[], "
                    "'ok', ARRAY[]::varchar[], 'pending'"
                    ")"
                ),
                {"id": rid, "ts": timestamp, "sid": uuid.uuid4()},
            )
            await conn.execute(
                text(
                    "INSERT INTO corpus.raw_record (id, raw_payload, created_at) "
                    "VALUES (:id, CAST(:p AS JSONB), :ts)"
                ),
                {
                    "id": rid,
                    "ts": timestamp,
                    "p": (
                        f'{{"capture_level": "full", "natural_language_question": "record {i}"}}'
                    ),
                },
            )
    return ids


async def test_replay_processes_all_pending() -> None:
    ids = await _seed_pending_records(3, timestamp=datetime.now(tz=UTC))
    engine = get_engine()
    worker = SanitiserWorker(
        engine,
        SanitisationPipeline(rules=[StripDirectIdentifiers()]),
        CONFIG,
    )

    count = await replay_pending(engine, worker)

    assert count == 3
    async with engine.connect() as conn:
        statuses = (
            await conn.execute(text("SELECT review_status FROM corpus.question_record"))
        ).all()
    assert all(row.review_status == "cleared" for row in statuses)
    # All ids accounted for.
    async with engine.connect() as conn:
        seen_ids = {
            row.id
            for row in (await conn.execute(text("SELECT id FROM corpus.question_record"))).all()
        }
    assert seen_ids == set(ids)


async def test_replay_since_filters_by_timestamp() -> None:
    old = datetime.now(tz=UTC) - timedelta(days=10)
    new = datetime.now(tz=UTC)
    old_id = (await _seed_pending_records(1, timestamp=old))[0]
    # Seed a second batch on top (the seed helper wipes; we manually add).
    engine = get_engine()
    new_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO corpus.question_record ("
                "id, timestamp, session_id, consent_version, capture_level, "
                "tool_called, tool_inputs_redacted, geography_referenced, "
                "indicators_returned, sources_used, result_status, gap_signals, "
                "review_status"
                ") VALUES ("
                ":id, :ts, :sid, 'v1.0', 'full', 'find_place', "
                "'{}'::jsonb, '{}'::jsonb, ARRAY[]::varchar[], ARRAY[]::varchar[], "
                "'ok', ARRAY[]::varchar[], 'pending'"
                ")"
            ),
            {"id": new_id, "ts": new, "sid": uuid.uuid4()},
        )
        await conn.execute(
            text(
                "INSERT INTO corpus.raw_record (id, raw_payload, created_at) "
                "VALUES (:id, '{}'::jsonb, :ts)"
            ),
            {"id": new_id, "ts": new},
        )

    worker = SanitiserWorker(
        engine,
        SanitisationPipeline(rules=[StripDirectIdentifiers()]),
        CONFIG,
    )
    cutoff = datetime.now(tz=UTC) - timedelta(days=1)
    count = await replay_pending(engine, worker, since=cutoff)
    assert count == 1

    async with engine.connect() as conn:
        old_row = (
            await conn.execute(
                text("SELECT review_status FROM corpus.question_record WHERE id = :id"),
                {"id": old_id},
            )
        ).first()
        new_row = (
            await conn.execute(
                text("SELECT review_status FROM corpus.question_record WHERE id = :id"),
                {"id": new_id},
            )
        ).first()
    assert old_row.review_status == "pending"
    assert new_row.review_status == "cleared"


async def test_replay_respects_concurrency_cap() -> None:
    """A slow worker proves the semaphore caps concurrency."""
    await _seed_pending_records(8, timestamp=datetime.now(tz=UTC))
    engine = get_engine()

    in_flight = 0
    peak = 0

    class TrackingWorker:
        async def sanitise(self, record_id: uuid.UUID) -> None:
            nonlocal in_flight, peak
            del record_id
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1

    await replay_pending(engine, TrackingWorker(), max_concurrent=3)  # type: ignore[arg-type]
    assert peak <= 3


async def test_replay_skips_records_without_raw_record() -> None:
    """Orphan stubs (raw retention deleted them) shouldn't be retried."""
    engine = get_engine()
    orphan_id = uuid.uuid4()
    timestamp = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM corpus.raw_record"))
        await conn.execute(text("DELETE FROM corpus.question_record"))
        await conn.execute(
            text(
                "INSERT INTO corpus.question_record ("
                "id, timestamp, session_id, consent_version, capture_level, "
                "tool_called, tool_inputs_redacted, geography_referenced, "
                "indicators_returned, sources_used, result_status, gap_signals, "
                "review_status"
                ") VALUES ("
                ":id, :ts, :sid, 'v1.0', 'full', 'find_place', "
                "'{}'::jsonb, '{}'::jsonb, ARRAY[]::varchar[], ARRAY[]::varchar[], "
                "'ok', ARRAY[]::varchar[], 'pending'"
                ")"
            ),
            {"id": orphan_id, "ts": timestamp, "sid": uuid.uuid4()},
        )

    seen: list[uuid.UUID] = []

    class TrackingWorker:
        async def sanitise(self, record_id: uuid.UUID) -> None:
            seen.append(record_id)

    count = await replay_pending(engine, TrackingWorker())  # type: ignore[arg-type]
    assert count == 0
    assert seen == []


async def _placeholder(_payload: Any) -> Any:
    return _payload

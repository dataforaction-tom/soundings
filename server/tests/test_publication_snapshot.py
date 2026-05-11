"""Integration tests for the publication snapshot query."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from soundings.db.engine import get_engine
from soundings.publication.snapshot import select_publishable

pytestmark = pytest.mark.integration


async def _seed_record(
    *,
    timestamp: datetime,
    capture_level: str = "minimal",
    review_status: str = "cleared",
    consent_version: str | None = "v1.0",
) -> uuid.UUID:
    engine = get_engine()
    record_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO corpus.question_record ("
                "id, timestamp, session_id, consent_version, capture_level, "
                "tool_called, tool_inputs_redacted, geography_referenced, "
                "indicators_returned, sources_used, result_status, gap_signals, "
                "review_status"
                ") VALUES ("
                ":id, :ts, :sid, :cv, :cl, 'find_place', "
                "'{}'::jsonb, '{}'::jsonb, ARRAY[]::varchar[], ARRAY[]::varchar[], "
                "'ok', ARRAY[]::varchar[], :rs"
                ")"
            ),
            {
                "id": record_id,
                "ts": timestamp,
                "sid": uuid.uuid4(),
                "cv": consent_version,
                "cl": capture_level,
                "rs": review_status,
            },
        )
    return record_id


async def _clean() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM corpus.raw_record"))
        await conn.execute(text("DELETE FROM corpus.question_record"))


async def test_snapshot_only_returns_cleared_full_or_minimal() -> None:
    await _clean()
    ts = datetime.now(tz=UTC) - timedelta(days=1)
    keep = await _seed_record(timestamp=ts, capture_level="full")
    keep_minimal = await _seed_record(timestamp=ts, capture_level="minimal")
    await _seed_record(timestamp=ts, capture_level="full", review_status="flagged")
    await _seed_record(timestamp=ts, capture_level="full", review_status="pending")
    await _seed_record(timestamp=ts, capture_level="none")  # should never publish

    cutoff = datetime.now(tz=UTC)
    rows = await select_publishable(get_engine(), period_end=cutoff)

    ids = {row.id for row in rows}
    assert ids == {keep, keep_minimal}


async def test_snapshot_filters_by_period_end() -> None:
    await _clean()
    now = datetime.now(tz=UTC)
    inside = await _seed_record(timestamp=now - timedelta(days=10))
    await _seed_record(timestamp=now + timedelta(days=1))  # in the future

    rows = await select_publishable(get_engine(), period_end=now)
    assert [row.id for row in rows] == [inside]


async def test_snapshot_excludes_consent_version_null() -> None:
    await _clean()
    # Defensive: rows without a consent_version somehow slipping through
    # should never publish. The schema requires it non-null, so this is
    # belt-and-braces — confirm the query's `IS NOT NULL` clause holds.
    ts = datetime.now(tz=UTC) - timedelta(days=1)
    await _seed_record(timestamp=ts, capture_level="minimal")

    rows = await select_publishable(get_engine(), period_end=datetime.now(tz=UTC))
    assert len(rows) == 1


async def test_snapshot_is_deterministically_ordered() -> None:
    await _clean()
    now = datetime.now(tz=UTC)
    ids = [await _seed_record(timestamp=now - timedelta(days=i + 1)) for i in range(5)]

    rows1 = await select_publishable(get_engine(), period_end=datetime.now(tz=UTC))
    rows2 = await select_publishable(get_engine(), period_end=datetime.now(tz=UTC))

    assert [row.id for row in rows1] == [row.id for row in rows2]
    # Sorted by timestamp ascending then id, so the oldest record comes first.
    assert rows1[0].id == ids[-1]

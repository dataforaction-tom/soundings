"""Integration tests for the per-session full-consent rate limiter."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from soundings.capture.rate_limit import FullConsentRateLimiter
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_session_records(
    session_id: uuid.UUID,
    *,
    count: int,
    capture_level: str = "full",
    timestamp: datetime | None = None,
) -> None:
    engine = get_engine()
    ts = timestamp or datetime.now(tz=UTC)
    async with engine.begin() as conn:
        for _ in range(count):
            await conn.execute(
                text(
                    "INSERT INTO corpus.question_record ("
                    "id, timestamp, session_id, consent_version, capture_level, "
                    "tool_called, tool_inputs_redacted, geography_referenced, "
                    "indicators_returned, sources_used, result_status, gap_signals, "
                    "review_status"
                    ") VALUES ("
                    ":id, :ts, :sid, 'v1.0', :cl, 'find_place', "
                    "'{}'::jsonb, '{}'::jsonb, ARRAY[]::varchar[], ARRAY[]::varchar[], "
                    "'ok', ARRAY[]::varchar[], 'cleared'"
                    ")"
                ),
                {
                    "id": uuid.uuid4(),
                    "ts": ts,
                    "sid": session_id,
                    "cl": capture_level,
                },
            )


async def _clean() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM corpus.raw_record"))
        await conn.execute(text("DELETE FROM corpus.question_record"))


async def test_under_threshold_returns_false() -> None:
    await _clean()
    session_id = uuid.uuid4()
    await _seed_session_records(session_id, count=1)

    limiter = FullConsentRateLimiter(get_engine(), threshold=3, window=timedelta(hours=1))
    assert await limiter.should_downgrade(session_id) is False


async def test_at_threshold_returns_true() -> None:
    await _clean()
    session_id = uuid.uuid4()
    await _seed_session_records(session_id, count=3)

    limiter = FullConsentRateLimiter(get_engine(), threshold=3, window=timedelta(hours=1))
    assert await limiter.should_downgrade(session_id) is True


async def test_records_outside_window_dont_count() -> None:
    await _clean()
    session_id = uuid.uuid4()
    # Two records 2 hours ago — outside the 1-hour window.
    old = datetime.now(tz=UTC) - timedelta(hours=2)
    await _seed_session_records(session_id, count=2, timestamp=old)
    # One recent record.
    await _seed_session_records(session_id, count=1)

    limiter = FullConsentRateLimiter(get_engine(), threshold=2, window=timedelta(hours=1))
    assert await limiter.should_downgrade(session_id) is False


async def test_only_full_consent_records_count() -> None:
    await _clean()
    session_id = uuid.uuid4()
    # 3 minimal records shouldn't trip a full-consent limit.
    await _seed_session_records(session_id, count=3, capture_level="minimal")

    limiter = FullConsentRateLimiter(get_engine(), threshold=2, window=timedelta(hours=1))
    assert await limiter.should_downgrade(session_id) is False


async def test_other_sessions_dont_count() -> None:
    await _clean()
    session_a = uuid.uuid4()
    session_b = uuid.uuid4()
    await _seed_session_records(session_a, count=5)

    limiter = FullConsentRateLimiter(get_engine(), threshold=2, window=timedelta(hours=1))
    assert await limiter.should_downgrade(session_b) is False

"""Tests for POST /v1/capture/feedback — marked_useful + session auth."""

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text

from soundings.app import app
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_record(session_id: uuid.UUID) -> uuid.UUID:
    engine = get_engine()
    record_id = uuid.uuid4()
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
                ":id, :ts, :sid, 'v1.0', 'minimal', 'find_place', "
                "'{}'::jsonb, '{}'::jsonb, ARRAY[]::varchar[], ARRAY[]::varchar[], "
                "'ok', ARRAY[]::varchar[], 'cleared'"
                ")"
            ),
            {"id": record_id, "ts": datetime.now(tz=UTC), "sid": session_id},
        )
    return record_id


async def test_feedback_from_same_session_updates_marked_useful() -> None:
    session_id = uuid.uuid4()
    record_id = await _seed_record(session_id)

    transport = httpx.ASGITransport(app=app)
    cookies = {
        "soundings_session": str(session_id),
        "soundings_consent": "minimal",
    }
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        response = await client.post(
            "/v1/capture/feedback",
            json={"question_record_id": str(record_id), "marked_useful": True},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                text("SELECT marked_useful FROM corpus.question_record WHERE id = :id"),
                {"id": record_id},
            )
        ).first()
    assert row is not None
    assert row.marked_useful is True


async def test_feedback_from_different_session_is_forbidden() -> None:
    record_owner = uuid.uuid4()
    record_id = await _seed_record(record_owner)
    other_session = uuid.uuid4()

    transport = httpx.ASGITransport(app=app)
    cookies = {
        "soundings_session": str(other_session),
        "soundings_consent": "minimal",
    }
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        response = await client.post(
            "/v1/capture/feedback",
            json={"question_record_id": str(record_id), "marked_useful": True},
        )

    assert response.status_code == 403
    # Row was not updated.
    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                text("SELECT marked_useful FROM corpus.question_record WHERE id = :id"),
                {"id": record_id},
            )
        ).first()
    assert row is not None
    assert row.marked_useful is None


async def test_feedback_without_session_cookie_is_forbidden() -> None:
    session_id = uuid.uuid4()
    record_id = await _seed_record(session_id)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/capture/feedback",
            json={"question_record_id": str(record_id), "marked_useful": False},
        )

    assert response.status_code == 403


async def test_feedback_for_unknown_record_is_404() -> None:
    session_id = uuid.uuid4()
    transport = httpx.ASGITransport(app=app)
    cookies = {
        "soundings_session": str(session_id),
        "soundings_consent": "minimal",
    }
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        response = await client.post(
            "/v1/capture/feedback",
            json={"question_record_id": str(uuid.uuid4()), "marked_useful": True},
        )

    assert response.status_code == 404

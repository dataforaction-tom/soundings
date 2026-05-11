"""Integration tests for SanitiserWorker — DB round-trip + alert path."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from soundings.capture.sanitisation.config import load_sanitisation_config
from soundings.capture.sanitisation.direct_identifiers import StripDirectIdentifiers
from soundings.capture.sanitisation.normalise import NormaliseAskerPurpose
from soundings.capture.sanitisation.pipeline import SanitisationPipeline
from soundings.capture.sanitisation.protocol import SanitisationResult
from soundings.capture.sanitiser_worker import SanitiserWorker
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration

CONFIG = load_sanitisation_config()


async def _seed_pending(record_id: uuid.UUID, raw_payload: dict[str, Any]) -> None:
    engine = get_engine()
    session_id = uuid.uuid4()
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
            {"id": record_id, "ts": timestamp, "sid": session_id},
        )
        await conn.execute(
            text(
                "INSERT INTO corpus.raw_record (id, raw_payload, created_at) "
                "VALUES (:id, CAST(:p AS JSONB), :ts)"
            ),
            {"id": record_id, "ts": timestamp, "p": _json(raw_payload)},
        )


def _json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload)


async def test_worker_redacts_postcode_and_marks_cleared() -> None:
    record_id = uuid.uuid4()
    await _seed_pending(
        record_id,
        {
            "capture_level": "full",
            "tool_inputs": {"query": "Stockton"},
            "natural_language_question": "I live near TS18 1AB",
            "asker_sector": "charity",
            "asker_purpose": None,
            "geography_referenced": [{"id": "ltla24:E06000004", "type": "ltla24"}],
        },
    )

    pipeline = SanitisationPipeline(rules=[StripDirectIdentifiers(), NormaliseAskerPurpose()])
    worker = SanitiserWorker(engine=get_engine(), pipeline=pipeline, config=CONFIG)
    await worker.sanitise(record_id)

    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT review_status, sanitisation_rules_version, "
                    "natural_language_question, asker_sector, geography_referenced "
                    "FROM corpus.question_record WHERE id = :id"
                ),
                {"id": record_id},
            )
        ).first()

    assert row is not None
    assert row.review_status == "cleared"
    assert row.sanitisation_rules_version == CONFIG.version
    assert row.natural_language_question == "I live near TS18 1"
    assert row.asker_sector == "charity"
    assert row.geography_referenced == [{"id": "ltla24:E06000004", "type": "ltla24"}]


async def test_worker_flags_record_when_multiple_fires() -> None:
    record_id = uuid.uuid4()
    await _seed_pending(
        record_id,
        {
            "capture_level": "full",
            "tool_inputs": {},
            "natural_language_question": "mail tom@example.org or call 07700 900123",
            "asker_sector": None,
            "asker_purpose": None,
            "geography_referenced": [],
        },
    )

    pipeline = SanitisationPipeline(rules=[StripDirectIdentifiers()])
    worker = SanitiserWorker(engine=get_engine(), pipeline=pipeline, config=CONFIG)
    await worker.sanitise(record_id)

    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT review_status, natural_language_question "
                    "FROM corpus.question_record WHERE id = :id"
                ),
                {"id": record_id},
            )
        ).first()

    assert row is not None
    assert row.review_status == "flagged"
    assert "tom@example.org" not in row.natural_language_question
    assert "07700 900123" not in row.natural_language_question


async def test_worker_failure_leaves_record_pending_and_fires_alert() -> None:
    record_id = uuid.uuid4()
    await _seed_pending(
        record_id,
        {"capture_level": "full", "natural_language_question": "anything"},
    )

    class ExplodingRule:
        name = "exploder"

        def apply(self, payload: dict, config: object) -> SanitisationResult:
            del payload, config
            raise RuntimeError("boom")

    alert_calls: list[str] = []

    def fake_alert(subject: str, body: str, *, source: str) -> None:
        del body, source
        alert_calls.append(subject)

    pipeline = SanitisationPipeline(rules=[ExplodingRule()])
    worker = SanitiserWorker(
        engine=get_engine(), pipeline=pipeline, config=CONFIG, alert=fake_alert
    )
    await worker.sanitise(record_id)

    async with get_engine().connect() as conn:
        row = (
            await conn.execute(
                text("SELECT review_status FROM corpus.question_record WHERE id = :id"),
                {"id": record_id},
            )
        ).first()

    assert row is not None
    assert row.review_status == "pending"
    assert len(alert_calls) == 1
    assert "sanitiser" in alert_calls[0].lower()

"""Integration tests for RawRecordWriter.

Exercises the actual DB writes against `corpus.{question_record,
raw_record}`. The catalogue + corpus tables already exist from
migration 0004 (Phase 0).
"""

from uuid import uuid4

import pytest
from sqlalchemy import text

from soundings.capture.context import CaptureContext
from soundings.capture.raw_writer import RawRecordWriter
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _clean_corpus() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        # raw_record FK → question_record, so order matters.
        await conn.execute(text("DELETE FROM corpus.raw_record"))
        await conn.execute(text("DELETE FROM corpus.question_record"))


async def test_raw_writer_inserts_stub_question_and_raw_payload() -> None:
    await _clean_corpus()
    engine = get_engine()
    writer = RawRecordWriter(engine)

    session_id = uuid4()
    ctx = CaptureContext(
        session_id=session_id,
        consent_level="full",
        consent_version="v1.0",
        tool_called="find_place",
        tool_inputs={"query": "Stockton-on-Tees"},
        natural_language_question="What's the population of Stockton?",
        asker_sector="charity",
        asker_purpose=None,
        result_status="ok",
        error_class=None,
        indicators_returned=[],
        sources_used=[],
        geography_referenced=[{"id": "ltla24:E06000004", "type": "ltla24"}],
    )

    await writer.write(ctx)

    async with engine.connect() as conn:
        question_rows = (
            await conn.execute(
                text(
                    "SELECT id, session_id, capture_level, tool_called, result_status "
                    "FROM corpus.question_record"
                )
            )
        ).all()
        raw_rows = (await conn.execute(text("SELECT id, raw_payload FROM corpus.raw_record"))).all()

    assert len(question_rows) == 1
    assert len(raw_rows) == 1
    assert question_rows[0].session_id == session_id
    assert question_rows[0].capture_level == "full"
    assert question_rows[0].tool_called == "find_place"
    assert question_rows[0].result_status == "ok"
    # raw_record.id FKs to question_record.id — same UUID on both rows.
    assert question_rows[0].id == raw_rows[0].id
    # The raw payload retains the unredacted nl_question and inputs.
    payload = raw_rows[0].raw_payload
    assert payload["natural_language_question"] == "What's the population of Stockton?"
    assert payload["tool_inputs"] == {"query": "Stockton-on-Tees"}
    assert payload["asker_sector"] == "charity"


async def test_raw_writer_skips_write_when_consent_is_none() -> None:
    await _clean_corpus()
    engine = get_engine()
    writer = RawRecordWriter(engine)

    ctx = CaptureContext(
        session_id=None,
        consent_level="none",
        consent_version="v1.0",
        tool_called="find_place",
        tool_inputs={"query": "TS18 1AB"},
        natural_language_question=None,
        asker_sector=None,
        asker_purpose=None,
        result_status="ok",
        error_class=None,
        indicators_returned=[],
        sources_used=[],
        geography_referenced=[],
    )

    await writer.write(ctx)

    async with engine.connect() as conn:
        question_count = (
            await conn.execute(text("SELECT COUNT(*) FROM corpus.question_record"))
        ).scalar_one()
        raw_count = (
            await conn.execute(text("SELECT COUNT(*) FROM corpus.raw_record"))
        ).scalar_one()
    assert question_count == 0
    assert raw_count == 0

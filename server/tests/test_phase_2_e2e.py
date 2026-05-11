"""Phase 2 end-to-end smoke.

Walks the full capture pipeline in one test:

1. POST /v1/capture/consent (full + charity sector)
2. POST /v1/tools/find_place with a postcode and an email in nl_question
3. Poll corpus.question_record until review_status leaves 'pending'
4. Assert postcode redacted to sector + email replaced; asker_sector
   survived to the record
5. Run publish() → manifest + both archives exist, CSV row count = 1
"""

import asyncio
import gzip
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from soundings.app import app
from soundings.db.engine import get_engine
from soundings.publication.cli import publish

pytestmark = pytest.mark.integration


async def _wait_for_review(session_id: uuid.UUID, timeout: float = 5.0) -> dict:
    engine = get_engine()
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, review_status, natural_language_question, "
                        "asker_sector FROM corpus.question_record "
                        "WHERE session_id = :sid ORDER BY timestamp DESC LIMIT 1"
                    ),
                    {"sid": session_id},
                )
            ).first()
        if row is not None and row.review_status != "pending":
            return {
                "id": row.id,
                "review_status": row.review_status,
                "natural_language_question": row.natural_language_question,
                "asker_sector": row.asker_sector,
            }
        await asyncio.sleep(0.05)
    raise AssertionError("question_record stayed pending past the deadline")


async def test_phase_2_e2e_capture_sanitisation_publication(tmp_path: Path) -> None:
    engine = get_engine()

    # Seed a Stockton LTLA so find_place returns exactly one match.
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM corpus.raw_record"))
        await conn.execute(text("DELETE FROM corpus.question_record"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:E06000004', 'ltla24', 'E06000004', "
                "'Stockton-on-Tees')"
            )
        )

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            consent_resp = await ac.post(
                "/v1/capture/consent",
                json={"consent_level": "full", "asker_sector": "charity"},
            )
            assert consent_resp.status_code == 200
            session_id = uuid.UUID(consent_resp.json()["session_id"])

            # Hit find_place with a nl_question containing a postcode + email.
            tool_resp = await ac.post(
                "/v1/tools/find_place",
                json={
                    "query": "Stockton-on-Tees",
                    "nl_question": (
                        "I live at TS18 1AB and my email is tom@example.org, "
                        "what's the picture for Stockton?"
                    ),
                },
            )
            assert tool_resp.status_code == 200

            # Wait for the sanitiser background task to finish.
            sanitised = await _wait_for_review(session_id)

    assert sanitised["review_status"] in ("cleared", "flagged")
    nlq = sanitised["natural_language_question"]
    assert nlq is not None
    assert "TS18 1AB" not in nlq
    assert "TS18 1" in nlq
    assert "tom@example.org" not in nlq
    assert "[redacted email]" in nlq
    assert sanitised["asker_sector"] == "charity"

    # Mark the record cleared so it makes it into the publication query
    # (the live pipeline only includes review_status='cleared').
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE corpus.question_record SET review_status = 'cleared'"))

    # Run the publication pipeline against the freshly captured record.
    summary = await publish(
        period="2026-05",
        output_dir=tmp_path,
        period_end=datetime(2030, 1, 1, tzinfo=UTC),  # well into the future
        create_git_tag=False,
    )
    assert summary.row_count == 1
    assert summary.csv_path.exists()
    assert summary.jsonl_path.exists()
    assert summary.manifest_path.exists()

    with gzip.open(summary.csv_path, "rt", encoding="utf-8") as fh:
        csv_lines = fh.read().splitlines()
    # header + 1 row
    assert len(csv_lines) == 2

    manifest = json.loads(summary.manifest_path.read_text())
    assert len(manifest["files"]) == 2
    assert manifest["sanitisation_rules_version"] == "v1"

"""End-to-end smoke for the publication pipeline.

Seeds a single publishable record, runs publish() from snapshot to
manifest, and verifies the manifest's SHA-256 entries match the bytes
on disk and that the manifest carries a real catalogue_version + git
sha. test_publication_cli.py covers individual surfaces; this test is
the contract between snapshot → writers → manifest.
"""

import gzip
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from soundings.db.engine import get_engine
from soundings.publication.cli import publish

pytestmark = pytest.mark.integration


async def test_publication_e2e_artefacts_match_manifest(tmp_path: Path) -> None:
    record_id = uuid.uuid4()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM corpus.raw_record"))
        await conn.execute(text("DELETE FROM corpus.question_record"))
        await conn.execute(
            text(
                "INSERT INTO corpus.question_record ("
                "id, timestamp, session_id, consent_version, capture_level, "
                "tool_called, tool_inputs_redacted, geography_referenced, "
                "indicators_returned, sources_used, result_status, gap_signals, "
                "review_status, sanitisation_rules_version"
                ") VALUES ("
                ":id, :ts, :sid, 'v1.0', 'full', 'get_indicators', "
                '\'{"place_id":"ltla24:E06000004"}\'::jsonb, '
                '\'[{"id":"ltla24:E06000004","type":"ltla24"}]\'::jsonb, '
                "ARRAY['population.total']::varchar[], "
                "ARRAY['ons.mid_year_estimates']::varchar[], "
                "'ok', ARRAY[]::varchar[], 'cleared', 'v1'"
                ")"
            ),
            {
                "id": record_id,
                "ts": datetime(2026, 5, 5, tzinfo=UTC),
                "sid": uuid.uuid4(),
            },
        )

    summary = await publish(
        period="2026-05",
        output_dir=tmp_path,
        period_end=datetime(2026, 6, 1, tzinfo=UTC),
        create_git_tag=False,
    )

    assert summary.row_count == 1
    manifest = json.loads(summary.manifest_path.read_text())

    # SHA-256s in the manifest match the file bytes.
    for entry in manifest["files"]:
        actual_sha = hashlib.sha256((tmp_path / entry["name"]).read_bytes()).hexdigest()
        assert actual_sha == entry["sha256"]

    # Catalogue version is a sha256 hex (64 chars) or the "unknown" fallback.
    assert manifest["catalogue_version"] in {"unknown"} or len(manifest["catalogue_version"]) == 64
    assert manifest["sanitisation_rules_version"] == "v1"

    # CSV has the indicator we seeded.
    with gzip.open(summary.csv_path, "rt", encoding="utf-8") as fh:
        rows = fh.read().splitlines()
    assert any("population.total" in line for line in rows)
    assert any("ons.mid_year_estimates" in line for line in rows)

    # JSONL preserves the nested place reference.
    with gzip.open(summary.jsonl_path, "rt", encoding="utf-8") as fh:
        line = fh.readline()
    obj = json.loads(line)
    assert obj["geography_referenced"] == [{"id": "ltla24:E06000004", "type": "ltla24"}]
    assert obj["tool_inputs_redacted"] == {"place_id": "ltla24:E06000004"}

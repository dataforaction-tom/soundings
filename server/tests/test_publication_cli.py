"""Integration tests for the publish-corpus CLI."""

import gzip
import json
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from soundings.db.engine import get_engine
from soundings.publication.cli import publish

pytestmark = pytest.mark.integration


def _run_git(*args: str, cwd: Path) -> str:
    """Wrapper that suppresses ruff's partial-path warning once."""
    return subprocess.check_output(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        text=True,
    )


def _init_throwaway_repo(repo_dir: Path) -> None:
    repo_dir.mkdir()
    _run_git("init", "-q", cwd=repo_dir)
    _run_git(
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "--allow-empty",
        "-m",
        "init",
        cwd=repo_dir,
    )


async def _seed_one_publishable(timestamp: datetime) -> uuid.UUID:
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
                "review_status, sanitisation_rules_version"
                ") VALUES ("
                ":id, :ts, :sid, 'v1.0', 'minimal', 'find_place', "
                "'{}'::jsonb, '{}'::jsonb, ARRAY[]::varchar[], ARRAY[]::varchar[], "
                "'ok', ARRAY[]::varchar[], 'cleared', 'v1'"
                ")"
            ),
            {"id": record_id, "ts": timestamp, "sid": uuid.uuid4()},
        )
    return record_id


async def test_publish_emits_three_artefacts(tmp_path: Path) -> None:
    seeded_id = await _seed_one_publishable(datetime(2026, 5, 5, tzinfo=UTC))

    summary = await publish(
        period="2026-05",
        output_dir=tmp_path,
        period_end=datetime(2026, 6, 1, tzinfo=UTC),
        create_git_tag=False,
    )

    csv_path = tmp_path / "corpus-2026-05.csv.gz"
    jsonl_path = tmp_path / "corpus-2026-05.jsonl.gz"
    manifest_path = tmp_path / "manifest.json"
    assert csv_path.exists()
    assert jsonl_path.exists()
    assert manifest_path.exists()
    assert summary.row_count == 1

    # CSV has exactly the seeded row.
    with gzip.open(csv_path, "rt", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    # header + 1 data row.
    assert len(lines) == 2
    assert str(seeded_id) in lines[1]

    # Manifest names both archives.
    manifest = json.loads(manifest_path.read_text())
    names = {entry["name"] for entry in manifest["files"]}
    assert names == {"corpus-2026-05.csv.gz", "corpus-2026-05.jsonl.gz"}


async def test_publish_creates_local_git_tag(tmp_path: Path) -> None:
    """The tag step is opt-in to keep the suite from polluting git state.

    We invoke with create_git_tag=True against a throwaway repo.
    """
    await _seed_one_publishable(datetime(2026, 4, 5, tzinfo=UTC))

    fake_repo = tmp_path / "fake"
    _init_throwaway_repo(fake_repo)

    out_dir = fake_repo / "corpus-out"
    out_dir.mkdir()
    await publish(
        period="2026-04",
        output_dir=out_dir,
        period_end=datetime(2026, 5, 1, tzinfo=UTC),
        create_git_tag=True,
        git_cwd=fake_repo,
    )

    tags = _run_git("tag", "--list", cwd=fake_repo).split()
    assert "corpus-2026-04" in tags


async def test_publish_is_idempotent_on_existing_tag(tmp_path: Path) -> None:
    """Re-running the same period must not fail on the tag step."""
    await _seed_one_publishable(datetime(2026, 4, 5, tzinfo=UTC))

    fake_repo = tmp_path / "fake"
    _init_throwaway_repo(fake_repo)

    out_dir = fake_repo / "corpus-out"
    out_dir.mkdir()
    kwargs = {
        "period": "2026-04",
        "output_dir": out_dir,
        "period_end": datetime(2026, 5, 1, tzinfo=UTC),
        "create_git_tag": True,
        "git_cwd": fake_repo,
    }
    await publish(**kwargs)
    # Second call must not raise.
    await publish(**kwargs)

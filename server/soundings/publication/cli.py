"""publish-corpus CLI.

Pulls publishable records from `corpus.question_record`, writes the
three artefacts to `output_dir`, and optionally creates a local
`corpus-YYYY-MM` git tag for reproducibility. Pushing that tag is left
to the operator (global rule: don't push without confirmation).

Run with `python -m soundings.publication.cli` or `make publish-corpus`.
"""

import argparse
import asyncio
import hashlib
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from soundings.alerts import send_alert
from soundings.capture.sanitisation.config import load_sanitisation_config
from soundings.db.engine import get_engine
from soundings.publication.manifest import resolve_git_sha, write_manifest
from soundings.publication.snapshot import select_publishable
from soundings.publication.writers import write_csv, write_jsonl

logger = logging.getLogger(__name__)


@dataclass
class PublishSummary:
    output_dir: Path
    csv_path: Path
    jsonl_path: Path
    manifest_path: Path
    row_count: int
    git_tag_created: bool


async def publish(
    *,
    period: str,
    output_dir: Path,
    period_end: datetime,
    create_git_tag: bool = True,
    git_cwd: Path | None = None,
) -> PublishSummary:
    """Materialise the monthly corpus artefacts.

    `period_end` is the exclusive upper bound on `timestamp`. For a
    monthly publish, pass the first day of the following month.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    engine = get_engine()

    try:
        records = await select_publishable(engine, period_end=period_end)

        csv_path = output_dir / f"corpus-{period}.csv.gz"
        jsonl_path = output_dir / f"corpus-{period}.jsonl.gz"

        write_csv(records, csv_path)
        write_jsonl(records, jsonl_path)

        catalogue_version = await _resolve_catalogue_version(engine)
        sanitisation_version = load_sanitisation_config().version
        git_sha = resolve_git_sha() or "unknown"

        manifest_path = write_manifest(
            output_dir,
            files=[csv_path, jsonl_path],
            period=period,
            catalogue_version=catalogue_version,
            sanitisation_rules_version=sanitisation_version,
            generator_git_sha=git_sha,
        )

        tag_created = False
        if create_git_tag:
            tag_created = _create_tag_idempotent(f"corpus-{period}", cwd=git_cwd)

        return PublishSummary(
            output_dir=output_dir,
            csv_path=csv_path,
            jsonl_path=jsonl_path,
            manifest_path=manifest_path,
            row_count=len(records),
            git_tag_created=tag_created,
        )
    except Exception as exc:
        logger.exception("publish failed")
        send_alert(
            f"Publication failed for period {period}",
            f"Output dir: {output_dir}\nException: {exc!r}",
            source="publication",
        )
        raise


async def _resolve_catalogue_version(engine: object) -> str:
    """Read catalogue_version from any indicator row.

    The loader stamps the same sha256(indicators.yaml) on every row in
    one run, so we can grab any one. Falls back to a literal "unknown"
    if the catalogue isn't loaded — production won't hit that path.
    """
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        row = (
            await conn.execute(text("SELECT catalogue_version FROM catalogue.indicator LIMIT 1"))
        ).first()
    if row is None or row.catalogue_version is None:
        # Best-effort fallback so the publication completes in dev.
        catalogue_dir = Path(__file__).resolve().parent.parent.parent.parent / "catalogue"
        indicators_yaml = catalogue_dir / "indicators.yaml"
        if indicators_yaml.exists():
            return hashlib.sha256(indicators_yaml.read_bytes()).hexdigest()
        return "unknown"
    return str(row.catalogue_version)


def _create_tag_idempotent(tag: str, *, cwd: Path | None) -> bool:
    """Create the tag if it doesn't already exist. Returns True if created."""
    try:
        existing = subprocess.check_output(  # noqa: S603
            ["git", "tag", "--list", tag],  # noqa: S607
            cwd=cwd,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.warning("git tag --list failed; skipping tag step")
        return False
    if existing:
        logger.info("tag %s already exists; skipping", tag)
        return False
    try:
        subprocess.run(  # noqa: S603
            ["git", "tag", "-a", tag, "-m", f"Corpus snapshot {tag}"],  # noqa: S607
            cwd=cwd,
            check=True,
        )
    except subprocess.CalledProcessError:
        logger.exception("git tag failed")
        return False
    return True


def _previous_month_period(now: datetime) -> str:
    year, month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    return f"{year:04d}-{month:02d}"


def _start_of_month(period: str) -> datetime:
    year, month = period.split("-")
    return datetime(int(year), int(month), 1, tzinfo=UTC)


def _next_month_start(period: str) -> datetime:
    year, month = period.split("-")
    if month == "12":
        return datetime(int(year) + 1, 1, 1, tzinfo=UTC)
    return datetime(int(year), int(month) + 1, 1, tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="soundings-publish")
    parser.add_argument(
        "--period",
        default=_previous_month_period(datetime.now(tz=UTC)),
        help="Period to publish, format YYYY-MM. Defaults to last month.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("corpus"),
        help="Output directory (default: ./corpus).",
    )
    parser.add_argument(
        "--no-tag",
        action="store_true",
        help="Skip the local git tag step.",
    )
    args = parser.parse_args(argv)

    summary = asyncio.run(
        publish(
            period=args.period,
            output_dir=args.out,
            period_end=_next_month_start(args.period),
            create_git_tag=not args.no_tag,
        )
    )
    print(f"[publish] period={summary.row_count} rows → {summary.output_dir}")
    print(f"          csv: {summary.csv_path}")
    print(f"          jsonl: {summary.jsonl_path}")
    print(f"          manifest: {summary.manifest_path}")
    print(f"          git tag: {'created' if summary.git_tag_created else 'skipped'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

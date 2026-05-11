import csv
import gzip
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from soundings.publication.snapshot import PublishableRecord
from soundings.publication.writers import (
    CSV_COLUMN_ORDER,
    write_csv,
    write_jsonl,
)


def _make_record(
    *,
    asker_sector: str | None = None,
    asker_purpose: str | None = None,
    marked_useful: bool | None = None,
) -> PublishableRecord:
    return PublishableRecord(
        id=uuid.uuid4(),
        timestamp=datetime(2026, 5, 1, tzinfo=UTC),
        session_id=uuid.uuid4(),
        consent_version="v1.0",
        capture_level="minimal",
        tool_called="get_indicators",
        tool_inputs_redacted={"place_id": "ltla24:E06000004"},
        geography_referenced=[{"id": "ltla24:E06000004", "type": "ltla24"}],
        indicators_returned=["population.total"],
        sources_used=["ons.mid_year_estimates"],
        result_status="ok",
        error_class=None,
        asker_sector=asker_sector,
        asker_purpose=asker_purpose,
        marked_useful=marked_useful,
        natural_language_question=None,
        sanitisation_rules_version="v1",
    )


def test_csv_writer_emits_header_and_one_row_per_record(tmp_path: Path) -> None:
    records = [_make_record(asker_sector="charity"), _make_record()]
    target = tmp_path / "corpus.csv.gz"
    write_csv(records, target)

    with gzip.open(target, "rt", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        body = list(reader)

    assert header == list(CSV_COLUMN_ORDER)
    assert len(body) == 2


def test_csv_column_order_is_stable() -> None:
    # Locked so downstream consumers can rely on it. If you change the
    # order, bump the publication sanitisation_rules_version.
    assert CSV_COLUMN_ORDER == (
        "id",
        "timestamp",
        "session_id",
        "consent_version",
        "capture_level",
        "tool_called",
        "geography_types",
        "indicators_returned",
        "sources_used",
        "result_status",
        "asker_sector",
        "marked_useful",
    )


def test_jsonl_writer_emits_one_json_object_per_line(tmp_path: Path) -> None:
    records = [_make_record(asker_purpose="testing"), _make_record()]
    target = tmp_path / "corpus.jsonl.gz"
    write_jsonl(records, target)

    with gzip.open(target, "rt", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    # Nested shape preserved.
    assert parsed[0]["tool_inputs_redacted"] == {"place_id": "ltla24:E06000004"}
    assert parsed[0]["asker_purpose"] == "testing"


def test_csv_writer_is_byte_identical_across_runs(tmp_path: Path) -> None:
    records = [_make_record(asker_sector="researcher")]
    first = tmp_path / "first.csv.gz"
    second = tmp_path / "second.csv.gz"
    write_csv(records, first)
    write_csv(records, second)

    # Compare uncompressed bytes — gzip headers include a timestamp that
    # can vary between runs even with identical input.
    with gzip.open(first, "rb") as a, gzip.open(second, "rb") as b:
        assert a.read() == b.read()


def test_csv_writer_handles_empty_input(tmp_path: Path) -> None:
    target = tmp_path / "empty.csv.gz"
    write_csv([], target)
    with gzip.open(target, "rt", encoding="utf-8") as fh:
        content = fh.read()
    # Only header, no data rows.
    assert content.strip().splitlines() == [",".join(CSV_COLUMN_ORDER)]


def test_jsonl_writer_handles_empty_input(tmp_path: Path) -> None:
    target = tmp_path / "empty.jsonl.gz"
    write_jsonl([], target)
    with gzip.open(target, "rt", encoding="utf-8") as fh:
        assert fh.read() == ""


def test_helper_geography_types_flattens_list() -> None:
    # The CSV column 'geography_types' is a |-separated string of place
    # types pulled from each record's geography_referenced list.
    record = _make_record()
    record_two_places = PublishableRecord(
        **{
            **record.__dict__,
            "geography_referenced": [
                {"id": "ltla24:E06000004", "type": "ltla24"},
                {"id": "region:E12000001", "type": "region"},
            ],
        }
    )
    # Use the public write_csv via an in-memory path through tmp.
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".csv.gz") as fh:
        write_csv([record_two_places], Path(fh.name))
        fh.seek(0)
        with gzip.open(fh.name, "rt", encoding="utf-8") as gz:
            rows = list(csv.DictReader(gz))
    assert rows[0]["geography_types"] == "ltla24|region"

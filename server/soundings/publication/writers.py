"""CSV + JSONL writers for the monthly corpus publication.

Both writers consume a `list[PublishableRecord]` and emit a gzipped
file. The CSV is flattened-wide for human/spreadsheet consumption; the
JSONL preserves the full nested shape (tool_inputs, geography refs,
asker_purpose) for downstream consumers that want everything.

Determinism: writers fix the gzip mtime to 0 so two runs over the same
input produce byte-identical bytes. The snapshot query (Task 24) is
already deterministically ordered.
"""

import csv
import gzip
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

from soundings.publication.snapshot import PublishableRecord

CSV_COLUMN_ORDER: tuple[str, ...] = (
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


def write_csv(records: list[PublishableRecord], path: Path) -> None:
    with gzip.GzipFile(filename=str(path), mode="wb", mtime=0) as gz:
        text_stream = _TextWrapper(gz)
        writer = csv.writer(text_stream, lineterminator="\n")
        writer.writerow(CSV_COLUMN_ORDER)
        for record in records:
            writer.writerow(_csv_row(record))


def write_jsonl(records: list[PublishableRecord], path: Path) -> None:
    with gzip.GzipFile(filename=str(path), mode="wb", mtime=0) as gz:
        for record in records:
            line = json.dumps(_jsonl_obj(record), sort_keys=True, separators=(",", ":"))
            gz.write(line.encode("utf-8"))
            gz.write(b"\n")


def _csv_row(record: PublishableRecord) -> list[Any]:
    geography_types = _geography_types(record.geography_referenced)
    return [
        str(record.id),
        record.timestamp.isoformat(),
        str(record.session_id),
        record.consent_version,
        record.capture_level,
        record.tool_called,
        geography_types,
        "|".join(record.indicators_returned),
        "|".join(record.sources_used),
        record.result_status,
        record.asker_sector or "",
        "" if record.marked_useful is None else ("true" if record.marked_useful else "false"),
    ]


def _geography_types(referenced: object) -> str:
    if isinstance(referenced, list):
        types = [str(item.get("type", "")) for item in referenced if isinstance(item, dict)]
        return "|".join(t for t in types if t)
    return ""


def _jsonl_obj(record: PublishableRecord) -> dict[str, Any]:
    obj = asdict(record)
    # JSON-serialise the non-primitive types.
    return {key: _json_safe(value) for key, value in obj.items()}


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class _TextWrapper:
    """Tiny adapter so csv.writer can write into a binary gzip stream."""

    def __init__(self, binary_stream: Any) -> None:
        self._inner = binary_stream

    def write(self, data: str) -> int:
        written = self._inner.write(data.encode("utf-8"))
        return int(written)

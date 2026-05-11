import gzip
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from soundings.publication.manifest import write_manifest


def _make_gzipped_file(path: Path, content: str) -> None:
    with gzip.GzipFile(filename=str(path), mode="wb", mtime=0) as gz:
        gz.write(content.encode("utf-8"))


def test_manifest_records_file_sha256_and_size(tmp_path: Path) -> None:
    csv_path = tmp_path / "corpus-2026-05.csv.gz"
    jsonl_path = tmp_path / "corpus-2026-05.jsonl.gz"
    _make_gzipped_file(csv_path, "id,timestamp\n1,2026-05-01T00:00:00\n")
    _make_gzipped_file(jsonl_path, '{"id":"1"}\n')

    manifest_path = write_manifest(
        tmp_path,
        files=[csv_path, jsonl_path],
        period="2026-05",
        catalogue_version="abc123" * 10 + "1234",  # 64 hex chars
        sanitisation_rules_version="v1",
        generator_git_sha="deadbeef",
    )

    assert manifest_path == tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["period"] == "2026-05"
    assert manifest["catalogue_version"] == "abc123" * 10 + "1234"
    assert manifest["sanitisation_rules_version"] == "v1"
    assert manifest["generator_git_sha"] == "deadbeef"

    csv_entry = next(f for f in manifest["files"] if f["name"] == csv_path.name)
    expected_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    assert csv_entry["sha256"] == expected_sha
    assert csv_entry["size_bytes"] == csv_path.stat().st_size


def test_manifest_files_use_basename_not_full_path(tmp_path: Path) -> None:
    csv_path = tmp_path / "corpus-2026-05.csv.gz"
    _make_gzipped_file(csv_path, "x")

    manifest_path = write_manifest(
        tmp_path,
        files=[csv_path],
        period="2026-05",
        catalogue_version="v1",
        sanitisation_rules_version="v1",
        generator_git_sha="abc",
    )
    manifest = json.loads(manifest_path.read_text())
    # No absolute paths inside the manifest — keeps it portable.
    assert manifest["files"][0]["name"] == "corpus-2026-05.csv.gz"
    assert "/" not in manifest["files"][0]["name"]


def test_manifest_is_deterministic(tmp_path: Path) -> None:
    csv_path = tmp_path / "corpus-2026-05.csv.gz"
    _make_gzipped_file(csv_path, "hello world")
    common_args = {
        "files": [csv_path],
        "period": "2026-05",
        "catalogue_version": "v1",
        "sanitisation_rules_version": "v1",
        "generator_git_sha": "abc",
    }
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    out_a.mkdir()
    out_b.mkdir()
    write_manifest(out_a, **common_args)
    write_manifest(out_b, **common_args)
    assert (out_a / "manifest.json").read_bytes() == (out_b / "manifest.json").read_bytes()


def test_resolve_git_sha_returns_current_head(tmp_path: Path) -> None:
    """Smoke check that the helper invokes git correctly."""
    from soundings.publication.manifest import resolve_git_sha

    sha = resolve_git_sha()
    # Locally we're inside a git repo, so this should be a real sha.
    if sha is not None:
        assert len(sha) == 40
        # Sanity: matches `git rev-parse HEAD`.
        expected = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            text=True,
        ).strip()
        assert sha == expected
    else:
        pytest.skip("not a git repo")

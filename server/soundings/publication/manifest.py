"""manifest.json for monthly publication.

Records the SHA-256 of every published file plus the active
catalogue_version, sanitisation_rules_version, and generator git sha
so a downstream consumer can verify exactly which inputs produced the
artefacts and reproduce the run.
"""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def write_manifest(
    output_dir: Path,
    *,
    files: list[Path],
    period: str,
    catalogue_version: str,
    sanitisation_rules_version: str,
    generator_git_sha: str,
) -> Path:
    """Emit `manifest.json` in `output_dir` referencing each file by name."""
    entries: list[dict[str, Any]] = []
    for path in files:
        data = path.read_bytes()
        entries.append(
            {
                "name": path.name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    manifest = {
        "period": period,
        "files": entries,
        "catalogue_version": catalogue_version,
        "sanitisation_rules_version": sanitisation_rules_version,
        "generator_git_sha": generator_git_sha,
    }
    target = output_dir / "manifest.json"
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return target


def resolve_git_sha() -> str | None:
    """`git rev-parse HEAD` — returns None outside a git repo."""
    try:
        # Trusted argv (literal list); PATH lookup is fine for portability.
        result = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout.strip() or None

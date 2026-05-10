"""Pydantic loader for `catalogue/nomis-mapping.yaml`.

Each entry binds a Soundings indicator key to a Nomis dataset query. Field
codes (`measures`, `cell`, `c2021_*`) are Nomis-specific and pinned per
indicator. Treat any `(unverified)` mapping as needing a sanity-check at
first run, same pattern as ADR-0001 endpoint URLs.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class NomisMapping(BaseModel):
    indicator_key: str
    source_id: str
    dataset_id: str
    measures: str | None = None
    cell: str | None = None
    geography_type_codes: dict[str, str] = Field(default_factory=dict)
    extra_params: dict[str, Any] = Field(default_factory=dict)
    period: str | None = None  # e.g. "2021" for Census, "latest" for MYE


def load_nomis_mapping(path: Path) -> list[NomisMapping]:
    raw = yaml.safe_load(path.read_text())
    items = raw.get("mappings", raw) if isinstance(raw, dict) else raw
    return [NomisMapping(**m) for m in items]

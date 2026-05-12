"""Pydantic loader for catalogue/statxplore-mapping.yaml.

Each entry pins one soundings indicator key to the Stat-Xplore cube
identifiers needed to query it. Identifiers are long opaque strings
that must match Stat-Xplore's schema exactly; mapping entries are
unverified until exercised against a live API key.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "catalogue"
    / "statxplore-mapping.yaml"
)


class StatXploreMapping(BaseModel):
    indicator_key: str
    database: str
    measures: list[str]
    geography_dim: str
    geography_value_template: str  # contains "{place_code}"
    date_dim: str
    place_type: str  # the soundings place type, e.g. "ltla24"
    unit: str = "count"
    caveats: list[str] = Field(default_factory=list)


def load_statxplore_mapping(path: Path | None = None) -> list[StatXploreMapping]:
    target = path or DEFAULT_MAPPING_PATH
    raw = yaml.safe_load(target.read_text())
    items = raw.get("mappings", raw) if isinstance(raw, dict) else raw
    return [StatXploreMapping(**m) for m in items]

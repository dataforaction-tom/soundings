"""Pydantic loader for catalogue/fingertips-mapping.yaml.

Each entry binds a soundings indicator key to a Fingertips
(profile_id, group_id, indicator_id, sex_id, age_id, child_area_type_id)
tuple. The adapter fetches a whole (profile × group × area_type) page
at once and filters down to the requested indicator + sex + age + place.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "catalogue"
    / "fingertips-mapping.yaml"
)


class FingertipsMapping(BaseModel):
    indicator_key: str
    profile_id: int
    group_id: int
    indicator_id: int
    sex_id: int
    age_id: int = 1
    child_area_type_id: int
    place_type: str  # the soundings place type, e.g. "ltla24"
    parent_area_code: str = "E92000001"  # England by default
    unit: str = "years"
    caveats: list[str] = Field(default_factory=list)


def load_fingertips_mapping(path: Path | None = None) -> list[FingertipsMapping]:
    target = path or DEFAULT_MAPPING_PATH
    raw = yaml.safe_load(target.read_text())
    items = raw.get("mappings", raw) if isinstance(raw, dict) else raw
    return [FingertipsMapping(**m) for m in items]

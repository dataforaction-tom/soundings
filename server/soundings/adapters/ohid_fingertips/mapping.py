"""Pydantic loader for catalogue/fingertips-mapping.yaml.

Same shape pattern as `soundings.adapters.nomis.mapping`. Each entry
binds a soundings indicator key to a Fingertips (indicator_id +
area_type_id + filter) tuple. The adapter filters Fingertips' returned
rows by Sex/Age columns post-query because the API doesn't accept
those as filter params.
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
    indicator_id: int
    child_area_type_id: int
    place_type: str  # the soundings place type, e.g. "ltla24"
    sex: str | None = None
    age: str | None = None
    unit: str = "years"
    parent_area_type_id: int | None = None
    caveats: list[str] = Field(default_factory=list)


def load_fingertips_mapping(path: Path | None = None) -> list[FingertipsMapping]:
    target = path or DEFAULT_MAPPING_PATH
    raw = yaml.safe_load(target.read_text())
    items = raw.get("mappings", raw) if isinstance(raw, dict) else raw
    return [FingertipsMapping(**m) for m in items]

"""Loader for `catalogue/sanitisation.yaml`.

Pydantic-validated thresholds for the sanitisation pipeline. Loaded once
at app startup and passed through each rule's `apply()` call. Bumping
`version` is the trigger to re-run the sanitiser on historical
raw_record rows (`soundings.capture.replay`, Task 19).
"""

from pathlib import Path

import yaml
from pydantic import BaseModel

# Repo layout: server/soundings/capture/sanitisation/config.py
#                                  ↑ four parents up = repo root
DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent / "catalogue" / "sanitisation.yaml"
)


class SmallOrgConfig(BaseModel):
    income_threshold_gbp: int


class AskerPurposeRateLimit(BaseModel):
    full_consent_per_session_per_hour: int


class AskerPurposeConfig(BaseModel):
    max_chars: int
    rate_limit: AskerPurposeRateLimit


class GeographyConfig(BaseModel):
    redact_finer_than: str  # place type, e.g. "msoa21"


class SanitisationConfig(BaseModel):
    version: str
    small_org: SmallOrgConfig
    asker_purpose: AskerPurposeConfig
    geography: GeographyConfig


def load_sanitisation_config(path: Path | None = None) -> SanitisationConfig:
    target = path or DEFAULT_CONFIG_PATH
    raw = yaml.safe_load(target.read_text())
    return SanitisationConfig.model_validate(raw)

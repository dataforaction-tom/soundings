"""NormaliseAskerPurpose + ValidateConsentLevel.

Two cleanup rules at the tail of the pipeline:

- NormaliseAskerPurpose: collapses runs of whitespace and trims the
  asker_purpose field, then truncates to the configured max_chars.
  Truncation counts as a fire (signals over-long input was clipped);
  whitespace cleanup alone doesn't.

- ValidateConsentLevel: defensive belt-and-braces — if a record's
  capture_level is "none" for any reason (data corruption, a bypassed
  writer), drop everything except the marker. The publication query
  already excludes capture_level="none" rows but this rule guarantees
  even an accidentally-published row carries no payload.
"""

import re
from typing import Any

from soundings.capture.sanitisation.config import SanitisationConfig
from soundings.capture.sanitisation.protocol import SanitisationResult

_WHITESPACE = re.compile(r"\s+")


class NormaliseAskerPurpose:
    name = "normalise_asker_purpose"

    def apply(self, payload: dict[str, Any], config: SanitisationConfig) -> SanitisationResult:
        value = payload.get("asker_purpose")
        if not isinstance(value, str) or not value:
            return SanitisationResult(payload=payload)

        collapsed = _WHITESPACE.sub(" ", value).strip()
        max_chars = config.asker_purpose.max_chars
        if len(collapsed) > max_chars:
            truncated = collapsed[:max_chars]
            new_payload = dict(payload)
            new_payload["asker_purpose"] = truncated
            return SanitisationResult(
                payload=new_payload,
                fields_changed={"asker_purpose"},
                fires=1,
            )

        if collapsed != value:
            new_payload = dict(payload)
            new_payload["asker_purpose"] = collapsed
            return SanitisationResult(payload=new_payload, fields_changed={"asker_purpose"})

        return SanitisationResult(payload=payload)


class ValidateConsentLevel:
    name = "validate_consent_level"

    def apply(self, payload: dict[str, Any], config: SanitisationConfig) -> SanitisationResult:
        del config
        if payload.get("capture_level") == "none":
            # Keep only the marker so a downstream observer can see WHY
            # the payload is empty.
            return SanitisationResult(
                payload={"capture_level": "none"},
                fields_changed=set(payload.keys()) - {"capture_level"},
                fires=1,
            )
        return SanitisationResult(payload=payload)

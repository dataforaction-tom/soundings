"""StripFineGeographyInFreeText — redact LSOA/MSOA references.

In free-text fields (`natural_language_question`, `asker_purpose`),
replaces:
- LSOA codes matching `[EW]0\\d{7}` → `[redacted area]`
- Any name in `fine_place_names` (LSOA + MSOA names loaded from
  `geography.place` at pipeline-init time) → `[redacted area]`

Structured tool inputs are intentionally left alone — they're how the
tool was driven, not how the user described their question. The LSOA
code in `tool_inputs.place_id` is part of the answer's
`geography_referenced` summary; the publication query exposes that
field separately (and only at the level the user explicitly queried).

The rule takes its name list via constructor so the Task 14 pipeline
runner can load names from the DB once at startup and pass the same
instance to every per-record call.
"""

import re
from typing import Any

from soundings.capture.sanitisation.config import SanitisationConfig
from soundings.capture.sanitisation.protocol import SanitisationResult

FREE_TEXT_FIELDS = ("natural_language_question", "asker_purpose")

# England LSOAs are E0xxxxxxx, Welsh W0xxxxxxx. MSOA codes share the same
# E02 / W02 prefix shape but the design's redaction floor is LSOA-level,
# so the pattern catches both — over-redaction is acceptable, under is not.
_FINE_AREA_CODE = re.compile(r"\b[EW]0\d{7}\b")


class StripFineGeographyInFreeText:
    name = "strip_fine_geography"

    def __init__(self, fine_place_names: list[str]) -> None:
        # Sort longest-first so "Stockton 010A West" matches before
        # "Stockton 010A" within an overlap.
        sorted_names = sorted(set(fine_place_names), key=len, reverse=True)
        if sorted_names:
            self._name_pattern: re.Pattern[str] | None = re.compile(
                "|".join(re.escape(n) for n in sorted_names),
                re.IGNORECASE,
            )
        else:
            self._name_pattern = None

    def apply(self, payload: dict[str, Any], config: SanitisationConfig) -> SanitisationResult:
        del config
        fires = 0
        fields_changed: set[str] = set()
        new_payload: dict[str, Any] = dict(payload)

        for field_name in FREE_TEXT_FIELDS:
            value = payload.get(field_name)
            if not isinstance(value, str) or not value:
                continue
            new_value, fired = self._strip(value)
            if fired:
                new_payload[field_name] = new_value
                fires += fired
                fields_changed.add(field_name)

        return SanitisationResult(payload=new_payload, fields_changed=fields_changed, fires=fires)

    def _strip(self, text: str) -> tuple[str, int]:
        fires = 0

        def _replace(_match: re.Match[str]) -> str:
            nonlocal fires
            fires += 1
            return "[redacted area]"

        text = _FINE_AREA_CODE.sub(_replace, text)
        if self._name_pattern is not None:
            text = self._name_pattern.sub(_replace, text)
        return text, fires

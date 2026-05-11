"""StripSmallOrgNames — redact small-charity names from free text.

The Charity Commission publishes annual income on every registered
charity; orgs reporting income under
`sanitisation.small_org.income_threshold_gbp` are treated as
identifiable in context. The Task 14 pipeline runner loads small-org
names from `data.organisation` (populated by Phase 4) at startup and
passes the list to this rule's constructor.

For Phase 2 the `data.organisation` table is empty in production seeds,
so the rule is effectively dormant — but it's tested with fixture data
to lock the contract before Phase 4 fills the table.
"""

import re
from typing import Any

from soundings.capture.sanitisation.config import SanitisationConfig
from soundings.capture.sanitisation.fine_geography import FREE_TEXT_FIELDS
from soundings.capture.sanitisation.protocol import SanitisationResult

REDACTED_ORG = "[redacted org]"


class StripSmallOrgNames:
    name = "strip_small_orgs"

    def __init__(self, small_org_names: list[str]) -> None:
        # Longest-first so "Stockton Foodbank Trust" matches before
        # "Stockton Foodbank" within the same string.
        sorted_names = sorted(set(small_org_names), key=len, reverse=True)
        if sorted_names:
            self._pattern: re.Pattern[str] | None = re.compile(
                "|".join(re.escape(n) for n in sorted_names),
                re.IGNORECASE,
            )
        else:
            self._pattern = None

    def apply(self, payload: dict[str, Any], config: SanitisationConfig) -> SanitisationResult:
        del config  # threshold lookup happens at list-construction time
        if self._pattern is None:
            return SanitisationResult(payload=payload)

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
        assert self._pattern is not None  # narrowed by caller's check
        fires = 0

        def _replace(_match: re.Match[str]) -> str:
            nonlocal fires
            fires += 1
            return REDACTED_ORG

        return self._pattern.sub(_replace, text), fires

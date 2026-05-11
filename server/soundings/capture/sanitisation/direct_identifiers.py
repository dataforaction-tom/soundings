"""StripDirectIdentifiers — postcodes, emails, UK phone numbers.

These three classes account for the bulk of obvious direct identifiers
that appear in free-text questions. The rule walks every string in the
payload (recursively into dicts and lists), applies each pattern, and
counts one fire per match. Spec §8.3 names postcodes explicitly; emails
and phone numbers are additions surfaced by the plan-reviewer because
the spaCy NER pass alone (Task 11) doesn't catch them.

Conservative on phones: the pattern matches common UK landline / mobile
shapes (starts with 0, 9-13 digits with optional spaces) and accepts
false positives on bare long numbers. The cost of an over-redaction in
the corpus is low; the cost of leaking a real number is high.
"""

import re
from typing import Any

from soundings.capture.sanitisation.config import SanitisationConfig
from soundings.capture.sanitisation.protocol import SanitisationResult

# Unit postcode: 1–2 letters, 1 digit, optional letter/digit, optional space,
# 1 digit, 2 letters. Outward+inward together = unit; the first digit of
# the inward is the sector. We replace the inward suffix (last two letters)
# with the empty string to leave just outward + sector-digit.
_POSTCODE_UNIT = re.compile(
    r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d)[A-Z]{2}\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")
# UK-style: leading 0, 9–13 digits with optional internal spaces.
_UK_PHONE = re.compile(r"\b0(?:\s*\d){8,12}\b")


class StripDirectIdentifiers:
    name = "strip_direct_identifiers"

    def apply(self, payload: dict[str, Any], config: SanitisationConfig) -> SanitisationResult:
        del config  # rule doesn't need config thresholds
        fires = 0
        fields_changed: set[str] = set()
        new_payload = {}
        for key, value in payload.items():
            new_value, key_fires = _strip_value(value)
            new_payload[key] = new_value
            if key_fires > 0:
                fires += key_fires
                fields_changed.add(key)
        return SanitisationResult(payload=new_payload, fields_changed=fields_changed, fires=fires)


def _strip_value(value: Any) -> tuple[Any, int]:
    if isinstance(value, str):
        return _strip_string(value)
    if isinstance(value, dict):
        new_dict = {}
        total = 0
        for k, v in value.items():
            new_v, fires = _strip_value(v)
            new_dict[k] = new_v
            total += fires
        return new_dict, total
    if isinstance(value, list):
        new_list = []
        total = 0
        for item in value:
            new_item, fires = _strip_value(item)
            new_list.append(new_item)
            total += fires
        return new_list, total
    return value, 0


def _strip_string(text: str) -> tuple[str, int]:
    fires = 0

    def _postcode_replacement(match: re.Match[str]) -> str:
        nonlocal fires
        fires += 1
        outward = match.group(1)
        sector_digit = match.group(2)
        return f"{outward} {sector_digit}"

    text = _POSTCODE_UNIT.sub(_postcode_replacement, text)

    def _email_replacement(_match: re.Match[str]) -> str:
        nonlocal fires
        fires += 1
        return "[redacted email]"

    text = _EMAIL.sub(_email_replacement, text)

    def _phone_replacement(_match: re.Match[str]) -> str:
        nonlocal fires
        fires += 1
        return "[redacted phone]"

    text = _UK_PHONE.sub(_phone_replacement, text)

    return text, fires

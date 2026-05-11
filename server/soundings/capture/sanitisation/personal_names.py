"""StripPersonalNamesViaNER — redact PERSON entities via spaCy.

Runs the `en_core_web_sm` model over each free-text field and replaces
spans labelled PERSON with `[redacted name]`. The model loads once at
import time (per-process) and is shared by every per-record call —
spaCy pipelines are reusable across threads in their async-friendly
configuration.

If the model isn't installed (`make install-spacy` was never run),
construction raises an OSError loud and clear rather than silently
no-opping. The Task 14 pipeline runner is responsible for instantiating
this rule at startup so any missing model fails health-check time
rather than first-request time.
"""

from typing import TYPE_CHECKING, Any

from soundings.capture.sanitisation.config import SanitisationConfig
from soundings.capture.sanitisation.fine_geography import FREE_TEXT_FIELDS
from soundings.capture.sanitisation.protocol import SanitisationResult

if TYPE_CHECKING:  # avoid importing spacy at type-check time on hosts without it
    from spacy.language import Language

REDACTED_NAME = "[redacted name]"
_MODEL_NAME = "en_core_web_sm"
_nlp: "Language | None" = None


def _get_nlp() -> "Language":
    global _nlp
    if _nlp is None:
        import spacy

        _nlp = spacy.load(_MODEL_NAME)
    return _nlp


class StripPersonalNamesViaNER:
    name = "strip_personal_names"

    def __init__(self) -> None:
        # Eagerly load so misconfiguration shows up at startup.
        self._nlp = _get_nlp()

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
        doc = self._nlp(text)
        spans = [ent for ent in doc.ents if ent.label_ == "PERSON"]
        if not spans:
            return text, 0
        # Replace from the right so earlier offsets stay valid.
        result = text
        for ent in sorted(spans, key=lambda e: e.start_char, reverse=True):
            result = result[: ent.start_char] + REDACTED_NAME + result[ent.end_char :]
        return result, len(spans)

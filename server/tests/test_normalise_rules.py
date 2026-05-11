from soundings.capture.sanitisation.config import load_sanitisation_config
from soundings.capture.sanitisation.normalise import (
    NormaliseAskerPurpose,
    ValidateConsentLevel,
)

CONFIG = load_sanitisation_config()


def test_long_asker_purpose_is_truncated_with_fire() -> None:
    rule = NormaliseAskerPurpose()
    long_text = "x" * 300
    out = rule.apply({"asker_purpose": long_text}, CONFIG)
    assert len(out.payload["asker_purpose"]) == CONFIG.asker_purpose.max_chars
    assert out.fires == 1
    assert "asker_purpose" in out.fields_changed


def test_whitespace_is_collapsed_without_a_fire() -> None:
    rule = NormaliseAskerPurpose()
    out = rule.apply({"asker_purpose": "  hello   world  "}, CONFIG)
    assert out.payload["asker_purpose"] == "hello world"
    # Whitespace normalisation alone isn't worth flagging — it's cleanup.
    assert out.fires == 0


def test_missing_asker_purpose_is_a_noop() -> None:
    rule = NormaliseAskerPurpose()
    out = rule.apply({"asker_purpose": None, "natural_language_question": "hi"}, CONFIG)
    assert out.payload["asker_purpose"] is None
    assert out.fires == 0


def test_validate_consent_none_empties_payload() -> None:
    rule = ValidateConsentLevel()
    out = rule.apply(
        {
            "capture_level": "none",
            "natural_language_question": "should be discarded",
            "asker_purpose": "should be discarded",
        },
        CONFIG,
    )
    assert out.payload == {"capture_level": "none"}
    assert out.fires == 1


def test_validate_consent_minimal_passes_through() -> None:
    rule = ValidateConsentLevel()
    payload = {"capture_level": "minimal", "natural_language_question": None}
    out = rule.apply(payload, CONFIG)
    assert out.payload == payload
    assert out.fires == 0


def test_validate_consent_missing_field_is_safe_passthrough() -> None:
    # Defensive: raw_writer always includes capture_level, but if a future
    # caller passes a payload without it, the rule should not blow up.
    rule = ValidateConsentLevel()
    out = rule.apply({"natural_language_question": "hi"}, CONFIG)
    assert out.payload == {"natural_language_question": "hi"}
    assert out.fires == 0

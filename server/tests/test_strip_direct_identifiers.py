from soundings.capture.sanitisation.config import load_sanitisation_config
from soundings.capture.sanitisation.direct_identifiers import StripDirectIdentifiers

CONFIG = load_sanitisation_config()


def _apply(payload: dict) -> tuple[dict, int, set[str]]:
    result = StripDirectIdentifiers().apply(payload, CONFIG)
    return result.payload, result.fires, result.fields_changed


def test_unit_postcode_gets_truncated_to_sector() -> None:
    payload = {"natural_language_question": "I live in TS18 1AB."}
    out, fires, fields = _apply(payload)
    assert out["natural_language_question"] == "I live in TS18 1."
    assert fires == 1
    assert "natural_language_question" in fields


def test_email_address_gets_redacted() -> None:
    payload = {"natural_language_question": "reach me at tom@example.org"}
    out, fires, _ = _apply(payload)
    assert "tom@example.org" not in out["natural_language_question"]
    assert "[redacted email]" in out["natural_language_question"]
    assert fires == 1


def test_uk_phone_number_gets_redacted() -> None:
    payload = {"asker_purpose": "call 07700 900123 for context"}
    out, fires, _ = _apply(payload)
    assert "07700 900123" not in out["asker_purpose"]
    assert "[redacted phone]" in out["asker_purpose"]
    assert fires == 1


def test_multiple_classes_each_count_as_one_fire() -> None:
    payload = {
        "natural_language_question": ("I'm at TS18 1AB, mail tom@example.org or call 07700 900123.")
    }
    out, fires, _ = _apply(payload)
    assert fires == 3
    text = out["natural_language_question"]
    assert "TS18 1AB" not in text and "TS18 1" in text
    assert "tom@example.org" not in text
    assert "07700 900123" not in text


def test_sector_only_postcode_is_preserved() -> None:
    payload = {"natural_language_question": "the TS18 area has lots of activity"}
    out, fires, _ = _apply(payload)
    assert out["natural_language_question"] == "the TS18 area has lots of activity"
    assert fires == 0


def test_nested_string_fields_are_walked() -> None:
    payload = {
        "tool_inputs": {"query": "TS18 1AB", "filters": ["call 07700 900123"]},
        "natural_language_question": None,
    }
    out, fires, fields = _apply(payload)
    assert out["tool_inputs"]["query"] == "TS18 1"
    assert out["tool_inputs"]["filters"][0] == "call [redacted phone]"
    assert fires == 2
    assert "tool_inputs" in fields


def test_none_and_non_string_values_are_left_alone() -> None:
    payload = {
        "natural_language_question": None,
        "tool_inputs": {"count": 5},
        "asker_purpose": None,
    }
    out, fires, fields = _apply(payload)
    assert out == payload
    assert fires == 0
    assert fields == set()

from soundings.capture.sanitisation.config import load_sanitisation_config
from soundings.capture.sanitisation.fine_geography import StripFineGeographyInFreeText

CONFIG = load_sanitisation_config()


def _rule(*names: str) -> StripFineGeographyInFreeText:
    return StripFineGeographyInFreeText(fine_place_names=list(names))


def test_lsoa_code_in_free_text_is_redacted() -> None:
    out = _rule().apply({"natural_language_question": "E01012018 is interesting"}, CONFIG)
    assert "[redacted area]" in out.payload["natural_language_question"]
    assert "E01012018" not in out.payload["natural_language_question"]
    assert out.fires == 1


def test_welsh_lsoa_code_is_also_redacted() -> None:
    out = _rule().apply({"asker_purpose": "W01000123 needs more support"}, CONFIG)
    assert "W01000123" not in out.payload["asker_purpose"]
    assert "[redacted area]" in out.payload["asker_purpose"]
    assert out.fires == 1


def test_lsoa_place_name_is_redacted() -> None:
    out = _rule("Stockton 010A").apply(
        {"natural_language_question": "Stockton 010A is a deprived LSOA"}, CONFIG
    )
    assert "Stockton 010A" not in out.payload["natural_language_question"]
    assert "[redacted area]" in out.payload["natural_language_question"]
    assert out.fires == 1


def test_ltla_name_is_preserved() -> None:
    out = _rule("Stockton 010A").apply(
        {"natural_language_question": "Stockton-on-Tees has 200k people"}, CONFIG
    )
    assert "Stockton-on-Tees" in out.payload["natural_language_question"]
    assert out.fires == 0


def test_rule_only_walks_free_text_fields() -> None:
    out = _rule("Stockton 010A").apply(
        {
            # tool_inputs is structured data — should NOT be searched for
            # LSOA names because reduces precision (every LSOA query would
            # over-redact). Free-text fields are explicit.
            "tool_inputs": {"query": "Stockton 010A"},
            "natural_language_question": "Stockton 010A",
        },
        CONFIG,
    )
    assert "[redacted area]" in out.payload["natural_language_question"]
    assert out.payload["tool_inputs"]["query"] == "Stockton 010A"
    assert out.fires == 1


def test_empty_name_list_still_matches_lsoa_codes() -> None:
    out = _rule().apply({"natural_language_question": "E01000001 deprivation"}, CONFIG)
    assert "[redacted area]" in out.payload["natural_language_question"]
    assert out.fires == 1

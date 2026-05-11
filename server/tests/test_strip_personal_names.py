import pytest

from soundings.capture.sanitisation.config import load_sanitisation_config

# spaCy + en_core_web_sm is a heavy install; skip these tests if the
# model isn't on this box. CI runs `make install-spacy` before pytest.
spacy = pytest.importorskip("spacy")
try:
    spacy.load("en_core_web_sm")
    _MODEL_AVAILABLE = True
except OSError:
    _MODEL_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _MODEL_AVAILABLE, reason="en_core_web_sm model not installed locally"
)

from soundings.capture.sanitisation.personal_names import (  # noqa: E402
    StripPersonalNamesViaNER,
)

CONFIG = load_sanitisation_config()


def test_personal_name_in_free_text_is_redacted() -> None:
    rule = StripPersonalNamesViaNER()
    out = rule.apply({"natural_language_question": "Jennifer wants to know about Stockton"}, CONFIG)
    text = out.payload["natural_language_question"]
    assert "Jennifer" not in text
    assert "[redacted name]" in text
    assert out.fires >= 1
    assert "natural_language_question" in out.fields_changed


def test_no_personal_name_means_no_fire() -> None:
    # NB: `_sm` over-flags certain place names (e.g. "Stockton" is also a
    # surname). We pick a sentence that doesn't include those edge cases
    # so the test stays stable across spaCy model versions.
    rule = StripPersonalNamesViaNER()
    out = rule.apply(
        {"natural_language_question": "the population is around 200000"},
        CONFIG,
    )
    assert out.payload["natural_language_question"] == "the population is around 200000"
    assert out.fires == 0


def test_rule_only_walks_free_text_fields() -> None:
    rule = StripPersonalNamesViaNER()
    out = rule.apply(
        {
            "tool_inputs": {"query": "Jennifer Smith"},
            "natural_language_question": "Jennifer asked us to look this up",
            "asker_purpose": None,
        },
        CONFIG,
    )
    # tool_inputs is structured; rule must not touch it.
    assert out.payload["tool_inputs"]["query"] == "Jennifer Smith"
    # natural_language_question is free text; rule redacts.
    assert "Jennifer" not in out.payload["natural_language_question"]

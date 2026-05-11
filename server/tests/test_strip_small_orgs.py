from soundings.capture.sanitisation.config import load_sanitisation_config
from soundings.capture.sanitisation.small_orgs import StripSmallOrgNames

CONFIG = load_sanitisation_config()


def test_small_org_name_in_free_text_is_redacted() -> None:
    rule = StripSmallOrgNames(small_org_names=["North Tees Community Trust"])
    out = rule.apply(
        {"asker_purpose": "Looking at need around North Tees Community Trust."},
        CONFIG,
    )
    assert "North Tees Community Trust" not in out.payload["asker_purpose"]
    assert "[redacted org]" in out.payload["asker_purpose"]
    assert out.fires == 1
    assert "asker_purpose" in out.fields_changed


def test_org_not_in_list_is_preserved() -> None:
    rule = StripSmallOrgNames(small_org_names=["Tiny Charity 12345"])
    out = rule.apply(
        {"natural_language_question": "What about Cancer Research UK in Stockton?"},
        CONFIG,
    )
    assert out.payload["natural_language_question"] == "What about Cancer Research UK in Stockton?"
    assert out.fires == 0


def test_rule_with_empty_list_is_a_noop() -> None:
    rule = StripSmallOrgNames(small_org_names=[])
    payload = {"natural_language_question": "Anything", "asker_purpose": None}
    out = rule.apply(payload, CONFIG)
    assert out.payload == payload
    assert out.fires == 0
    assert out.fields_changed == set()


def test_rule_only_walks_free_text_fields() -> None:
    rule = StripSmallOrgNames(small_org_names=["Tiny Trust"])
    out = rule.apply(
        {
            "tool_inputs": {"query": "Tiny Trust"},
            "natural_language_question": "Tiny Trust is doing important work",
            "asker_purpose": None,
        },
        CONFIG,
    )
    # tool_inputs are structured queries; not the sanitisation target.
    assert out.payload["tool_inputs"]["query"] == "Tiny Trust"
    assert "Tiny Trust" not in out.payload["natural_language_question"]
    assert out.fires == 1


def test_match_is_case_insensitive() -> None:
    rule = StripSmallOrgNames(small_org_names=["Stockton Foodbank"])
    out = rule.apply(
        {"natural_language_question": "stockton foodbank serves a lot of people"},
        CONFIG,
    )
    assert "stockton foodbank" not in out.payload["natural_language_question"].lower()
    assert "[redacted org]" in out.payload["natural_language_question"]
    assert out.fires == 1

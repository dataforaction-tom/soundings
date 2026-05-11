from soundings.capture.sanitisation.config import load_sanitisation_config
from soundings.capture.sanitisation.protocol import (
    SanitisationResult,
    SanitisationRule,
)


class FakeAlwaysFiresRule:
    name = "fake_always"

    def apply(self, payload: dict, config: object) -> SanitisationResult:
        del config  # rule doesn't read config; this avoids the unused-arg warning
        return SanitisationResult(
            payload={**payload, "natural_language_question": "[redacted]"},
            fields_changed={"natural_language_question"},
            fires=1,
        )


def test_protocol_is_satisfied_by_a_minimal_rule() -> None:
    # Structural protocols don't need explicit subclassing; assert
    # `FakeAlwaysFiresRule` plays the SanitisationRule role.
    rule: SanitisationRule = FakeAlwaysFiresRule()
    config = load_sanitisation_config()
    result = rule.apply({"natural_language_question": "hi there"}, config)

    assert isinstance(result, SanitisationResult)
    assert result.fires == 1
    assert "natural_language_question" in result.fields_changed
    assert result.payload["natural_language_question"] == "[redacted]"


def test_sanitisation_result_empty_changes_means_no_fire() -> None:
    result = SanitisationResult(payload={}, fields_changed=set(), fires=0)
    assert result.fires == 0
    assert result.fields_changed == set()

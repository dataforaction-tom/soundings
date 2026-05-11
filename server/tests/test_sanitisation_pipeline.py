from soundings.capture.sanitisation.config import load_sanitisation_config
from soundings.capture.sanitisation.pipeline import PipelineOutcome, SanitisationPipeline
from soundings.capture.sanitisation.protocol import SanitisationResult

CONFIG = load_sanitisation_config()


class FireOnceRule:
    def __init__(self, name: str, target_field: str) -> None:
        self.name = name
        self._field = target_field

    def apply(self, payload: dict, config: object) -> SanitisationResult:
        del config
        if self._field not in payload:
            return SanitisationResult(payload=payload)
        new_payload = dict(payload)
        new_payload[self._field] = "[redacted]"
        return SanitisationResult(payload=new_payload, fields_changed={self._field}, fires=1)


class NoOpRule:
    name = "noop"

    def apply(self, payload: dict, config: object) -> SanitisationResult:
        del config
        return SanitisationResult(payload=payload)


def test_no_fires_yields_cleared() -> None:
    pipeline = SanitisationPipeline(rules=[NoOpRule(), NoOpRule()])
    outcome = pipeline.run({"natural_language_question": "anything"}, CONFIG)
    assert isinstance(outcome, PipelineOutcome)
    assert outcome.total_fires == 0
    assert outcome.rules_fired == []
    assert outcome.review_status == "cleared"


def test_single_fire_yields_cleared() -> None:
    pipeline = SanitisationPipeline(rules=[FireOnceRule("a", "natural_language_question")])
    outcome = pipeline.run({"natural_language_question": "anything"}, CONFIG)
    assert outcome.total_fires == 1
    assert outcome.rules_fired == ["a"]
    assert outcome.review_status == "cleared"


def test_two_rules_each_firing_once_yields_flagged() -> None:
    pipeline = SanitisationPipeline(
        rules=[
            FireOnceRule("a", "natural_language_question"),
            FireOnceRule("b", "asker_purpose"),
        ]
    )
    outcome = pipeline.run({"natural_language_question": "x", "asker_purpose": "y"}, CONFIG)
    assert outcome.total_fires == 2
    assert set(outcome.rules_fired) == {"a", "b"}
    assert outcome.review_status == "flagged"


def test_single_rule_firing_twice_also_yields_flagged() -> None:
    class FireTwiceRule:
        name = "fire_twice"

        def apply(self, payload: dict, config: object) -> SanitisationResult:
            del config
            return SanitisationResult(payload=payload, fields_changed={"asker_purpose"}, fires=2)

    pipeline = SanitisationPipeline(rules=[FireTwiceRule()])
    outcome = pipeline.run({"asker_purpose": "anything"}, CONFIG)
    assert outcome.total_fires == 2
    assert outcome.review_status == "flagged"


def test_pipeline_passes_mutated_payload_to_each_rule() -> None:
    # Rule B should observe rule A's mutation.
    rule_b_seen_payload: dict = {}

    class FirstRule:
        name = "first"

        def apply(self, payload: dict, config: object) -> SanitisationResult:
            del config
            return SanitisationResult(
                payload={"asker_purpose": "[redacted]"},
                fields_changed={"asker_purpose"},
                fires=1,
            )

    class SecondRule:
        name = "second"

        def apply(self, payload: dict, config: object) -> SanitisationResult:
            del config
            rule_b_seen_payload.update(payload)
            return SanitisationResult(payload=payload)

    pipeline = SanitisationPipeline(rules=[FirstRule(), SecondRule()])
    pipeline.run({"asker_purpose": "original"}, CONFIG)

    assert rule_b_seen_payload["asker_purpose"] == "[redacted]"

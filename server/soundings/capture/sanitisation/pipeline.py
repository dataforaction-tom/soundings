"""SanitisationPipeline — composes the per-record rules.

Rules are run in order; each one sees the payload as mutated by the
prior rule. After the last rule, the pipeline returns:

- the sanitised payload (what writes back to question_record)
- the total fire count across all rules
- the names of rules that fired at least once
- a `review_status`: "cleared" (no fires or one fire) or "flagged"
  (two or more fires across the pipeline).

The fire-count interpretation tracks the plan-reviewer's "multi-fire"
heuristic rather than spec §8.3's literal "one rule firing more than
once" — it's strictly more conservative (flags more records), which is
the right side to err on for a public corpus.

For production wiring, see `build_default_pipeline` (Task 16's
sanitiser worker assembles this with the spaCy model and small-org
list loaded from the DB).
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from soundings.capture.sanitisation.config import SanitisationConfig
from soundings.capture.sanitisation.protocol import SanitisationRule

ReviewStatus = Literal["cleared", "flagged"]


@dataclass
class PipelineOutcome:
    sanitised_payload: dict[str, Any]
    total_fires: int = 0
    rules_fired: list[str] = field(default_factory=list)
    review_status: ReviewStatus = "cleared"


class SanitisationPipeline:
    def __init__(self, rules: list[SanitisationRule]) -> None:
        self._rules = rules

    def run(self, payload: dict[str, Any], config: SanitisationConfig) -> PipelineOutcome:
        current: dict[str, Any] = dict(payload)
        total_fires = 0
        rules_fired: list[str] = []

        for rule in self._rules:
            result = rule.apply(current, config)
            current = result.payload
            if result.fires > 0:
                total_fires += result.fires
                rules_fired.append(rule.name)

        review_status: ReviewStatus = "flagged" if total_fires >= 2 else "cleared"
        return PipelineOutcome(
            sanitised_payload=current,
            total_fires=total_fires,
            rules_fired=rules_fired,
            review_status=review_status,
        )

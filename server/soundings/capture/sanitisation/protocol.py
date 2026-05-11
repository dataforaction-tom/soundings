"""SanitisationRule protocol + SanitisationResult.

Each rule is a small, pure-ish function-with-state that maps a raw
payload to a sanitised payload, recording which fields it touched and
how many times it fired. The pipeline (Task 14) composes a list of
rules and aggregates their fire counts to decide whether a record is
`cleared` or `flagged` for human review.

Rules are stateless apart from any compiled resources (regex,
ML model). They should be safe to share across threads/coroutines.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from soundings.capture.sanitisation.config import SanitisationConfig


@dataclass
class SanitisationResult:
    """The output of one rule's `apply()` call.

    `payload` is the (possibly mutated) payload to pass to the next rule
    in the pipeline. `fields_changed` is the set of top-level field
    names this rule modified. `fires` is how many distinct
    redactions/transformations this rule performed — used by the
    pipeline's flag-for-review heuristic.
    """

    payload: dict[str, Any]
    fields_changed: set[str] = field(default_factory=set)
    fires: int = 0


class SanitisationRule(Protocol):
    name: str

    def apply(self, payload: dict[str, Any], config: SanitisationConfig) -> SanitisationResult: ...

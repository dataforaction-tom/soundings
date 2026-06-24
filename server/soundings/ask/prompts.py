"""System prompt builder for the ask orchestrator.

Modes are knobs on the system prompt — they all use the same /v1/ask
endpoint and the same answer renderer. The mode is a per-request hint;
the model is allowed to flex if the user's free text expresses a different
intent.
"""

from typing import Literal

AskMode = Literal["open", "summary", "compare", "insight"]

_MODE_EMPHASIS: dict[AskMode, str] = {
    "open": (
        "You are a generalist. Pick whichever tools fit the question. Be thorough but concise."
    ),
    "summary": (
        "Emphasise breadth across all available domains. Aim for one "
        "indicator card per major domain. Close each section with a short "
        "narrative paragraph."
    ),
    "compare": (
        "Always include at least one compare-chart block. Ground your "
        "narrative in percentile framing. Resolve peers via compare_places' "
        "same-type peer universe."
    ),
    "insight": (
        "Lead with the deterministic signals from detect_insights. "
        "Include one insight-callout per signal, ordered by severity. "
        "Your narrative explains the 'so what' for each signal."
    ),
}

_SCOPE_DESCRIPTION = """\
Soundings answers questions about UK places using open data. The available
domains are: population, deprivation, economy, health, education, housing,
crime, and civil society. You have these tools:

- find_place: resolve a place name or postcode to a canonical geography ID
- get_place_profile: baseline summary of a place across domains
- get_indicators: fetch specific indicators for a place
- compare_places: compare a place against peers (percentile, rank, absolute, rate)
- get_trend: fetch a time series for an indicator at a place
- find_organisations_in_place: find charities and civil society orgs in a place
- get_civil_society_profile: summary of the charity sector in a place
- detect_insights: deterministic statistical signals (extreme
  percentiles, peer divergence, trend reversals)
- compose_answer: terminal — compose the final answer from typed blocks

If a question is out of scope (weather, news, opinions, advice, anything not
answerable by the tools above), respond with a single text block explaining
what Soundings can help with and suggest the user try summarising a place or
comparing two.
"""

_BLOCK_GUIDANCE = """\
Block types for compose_answer:
- text: markdown prose (use for narrative, explanations, context)
- indicator-card: a single indicator value for a place
- trend-chart: a time-series chart for one indicator at one place
- compare-chart: a bar chart comparing an indicator across 2-10 places
- organisations: a list of civil society organisations in a place
- insight-callout: a severity-coloured callout for a notable signal

Limits: max 20 blocks total, max 6 visual blocks (everything except text).
Always interleave text with visual blocks — never put all charts at the end.
"""


class SystemPromptBuilder:
    """Builds the system prompt with mode-specific emphasis and optional
    pinned-place context."""

    def __init__(
        self,
        mode: AskMode = "open",
        place_name: str | None = None,
        place_id: str | None = None,
    ) -> None:
        if mode not in _MODE_EMPHASIS:
            raise ValueError(f"Invalid mode: {mode}")
        self.mode = mode
        self.place_name = place_name
        self.place_id = place_id

    def build(self) -> str:
        parts: list[str] = [
            "You are Soundings, an AI assistant that answers questions about"
            " UK places using open data.",
            "",
            _SCOPE_DESCRIPTION,
            "",
            f"Mode: {self.mode}. {_MODE_EMPHASIS[self.mode]}",
            "",
            _BLOCK_GUIDANCE,
        ]
        if self.place_name and self.place_id:
            parts.extend(
                [
                    "",
                    f"The user is asking about {self.place_name} (ID:"
                    f" {self.place_id}). Use this place_id directly unless the"
                    " user asks about a different place.",
                ]
            )
        return "\n".join(parts)

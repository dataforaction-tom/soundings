"""compare_places tool — per-indicator comparison against a peer universe.

Per spec §4.4. The caller supplies a highlighted subset of places + a list
of indicators; the orchestrator computes the comparison against every
same-type peer (full type universe), then attaches rank/percentile to the
highlighted subset.

`comparison_basis` is **explicitly optional with no default in spec §4.4**.
This plan ships percentile as the default because "how does my place
compare against its peers" is the most useful framing and the spec leaves
the default open. Recorded as a plan decision in the commit message that
introduced this schema.
"""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from soundings.contracts.comparison import Comparison
from soundings.contracts.source_ref import SourceRef

if TYPE_CHECKING:
    from soundings.orchestration.orchestrator import IndicatorOrchestrator

ComparisonBasis = Literal["percentile", "rank", "absolute", "rate"]


class ComparePlacesInput(BaseModel):
    place_ids: list[str]
    indicators: list[str]
    comparison_basis: ComparisonBasis = "percentile"
    period: str | None = None


class ComparePlacesOutput(BaseModel):
    results: list[Comparison] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    partial: bool = False


TOOL_NAME = "compare_places"
TOOL_DESCRIPTION = (
    "Compare a set of places against their full same-type peer universe "
    "for one or more indicators. Returns rank or percentile for each "
    "highlighted place; the peer denominator is always the complete set "
    "of places sharing the highlighted places' geography type."
)


def tool_spec() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": ComparePlacesInput.model_json_schema(),
        "output_schema": ComparePlacesOutput.model_json_schema(),
    }


async def compare_places(
    input: ComparePlacesInput, orchestrator: "IndicatorOrchestrator"
) -> ComparePlacesOutput:
    result = await orchestrator.compare_places(
        place_ids=input.place_ids,
        indicators=input.indicators,
        basis=input.comparison_basis,
        period=input.period,
    )
    return ComparePlacesOutput(
        results=result.comparisons,
        sources=result.sources,
        caveats=result.caveats,
        partial=result.partial,
    )

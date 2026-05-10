"""get_indicators tool — targeted indicator lookup per spec §4.3.

Fans out across the orchestrator. Wide vs tall format post-shape is applied
on the way out; both formats share the deduplicated SourceRef[].
"""

from typing import Literal

from pydantic import BaseModel, Field

from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.source_ref import SourceRef
from soundings.orchestration.orchestrator import IndicatorOrchestrator


class GetIndicatorsInput(BaseModel):
    place_id: str
    indicators: list[str]
    period: str | None = None
    format: Literal["wide", "tall"] = "tall"


class WideRow(BaseModel):
    place_id: str
    indicators: dict[str, float | None]


class GetIndicatorsOutput(BaseModel):
    results: list[IndicatorValue] = Field(default_factory=list)
    wide: WideRow | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    partial: bool = False


async def get_indicators(
    input: GetIndicatorsInput, orchestrator: IndicatorOrchestrator
) -> GetIndicatorsOutput:
    result = await orchestrator.fetch(
        indicator_keys=input.indicators,
        place_id=input.place_id,
        period=input.period,
    )
    wide: WideRow | None = None
    if input.format == "wide":
        wide = WideRow(
            place_id=input.place_id,
            indicators={v.indicator: v.value for v in result.values},
        )
    return GetIndicatorsOutput(
        results=result.values,
        wide=wide,
        sources=result.sources,
        caveats=result.caveats,
        partial=result.partial,
    )


TOOL_NAME = "get_indicators"
TOOL_DESCRIPTION = (
    "Look up specific indicator values for a single place. Returns a list of "
    "IndicatorValue entries with provenance and cache_status."
)


def tool_spec() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": GetIndicatorsInput.model_json_schema(),
        "output_schema": GetIndicatorsOutput.model_json_schema(),
    }

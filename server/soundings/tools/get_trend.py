"""get_trend tool — time series for one indicator at one place.

Per spec §4.5. Routes to the indicator's adapter:
- Loader-mode adapters serve from `data.trend_point` (Phase 3 ships
  the SELECT path; future loaders populate the table).
- Passthrough-mode adapters call `adapter.fetch_trend` and rely on the
  per-source cache.

`breaks_in_series` is populated from `catalogue.indicator.caveats`
filtered to the `"series_break:"` prefix per the Phase 3 plan Task 2
convention. Other catalogue caveats surface in `caveats` on the output.
"""

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from soundings.contracts.source_ref import SourceRef
from soundings.contracts.trend import Trend

if TYPE_CHECKING:
    from soundings.orchestration.orchestrator import IndicatorOrchestrator


class GetTrendInput(BaseModel):
    place_id: str
    indicator: str
    period_from: str | None = None
    period_to: str | None = None


class GetTrendOutput(BaseModel):
    trend: Trend | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    partial: bool = False


TOOL_NAME = "get_trend"
TOOL_DESCRIPTION = (
    "Return the time series for one indicator at one place, optionally "
    "windowed by period_from / period_to. Series breaks are surfaced in "
    "Trend.breaks_in_series so the consumer can disclaim cross-break "
    "comparisons."
)


def tool_spec() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": GetTrendInput.model_json_schema(),
        "output_schema": GetTrendOutput.model_json_schema(),
    }


async def get_trend(input: GetTrendInput, orchestrator: "IndicatorOrchestrator") -> GetTrendOutput:
    result = await orchestrator.get_trend(
        indicator_key=input.indicator,
        place_id=input.place_id,
        period_from=input.period_from,
        period_to=input.period_to,
    )
    return GetTrendOutput(
        trend=result.trend,
        sources=result.sources,
        caveats=result.caveats,
        partial=result.partial,
    )

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
    # Phase 3 Task 32 ships the schema; Task 33 wires
    # `orchestrator.get_trend` and replaces this body.
    raise NotImplementedError("get_trend orchestrator path wired in Phase 3 Task 33")

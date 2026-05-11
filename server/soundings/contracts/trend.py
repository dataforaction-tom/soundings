"""Trend + TrendPoint — time-series response shape for `get_trend`.

Per spec §4.5. `breaks_in_series` is populated by the orchestrator
from `catalogue.indicator.caveats` entries prefixed with
`series_break:` (Phase 3 plan Task 2 convention).
"""

from pydantic import BaseModel, Field

from soundings.contracts.source_ref import SourceRef


class TrendPoint(BaseModel):
    period: str
    value: float | None
    revised: bool = False


class Trend(BaseModel):
    place_id: str
    indicator: str
    unit: str
    points: list[TrendPoint] = Field(default_factory=list)
    source: SourceRef
    breaks_in_series: list[str] = Field(default_factory=list)

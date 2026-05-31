from typing import Literal

from pydantic import BaseModel, Field

from soundings.contracts.source_ref import SourceRef

# v1 reserves "experiential" for v3 contributed observations. Loader-mode
# adapters return "official" or "modelled"; passthrough adapters serving
# experimental data sources can return "experimental".
Confidence = Literal["official", "modelled", "experimental"]


class IndicatorValue(BaseModel):
    """A single indicator value at a single place at a single period.

    Per spec §4.3 / design §3. The shape returned by every adapter's
    `fetch_indicator` and by every tool that yields indicator data.
    """

    place_id: str
    indicator: str
    value: float | None
    unit: str
    period: str
    source: SourceRef
    methodology_note: str | None = None
    caveats: list[str] = Field(default_factory=list)
    confidence: Confidence
    # Directionality from catalogue.indicator.higher_is — informs the UI's
    # good/bad framing on the benchmark badge. None for indicators where
    # direction depends on context (e.g. raw counts).
    higher_is: Literal["better", "worse", "neutral"] | None = None
    # Percentile of this value against peer places of the same type (same
    # place.type), excluding self. Populated by tools that have access to
    # the full peer universe in data.indicator_value (loader-mode); None
    # when no peer data is loaded.
    benchmark_percentile: float | None = None

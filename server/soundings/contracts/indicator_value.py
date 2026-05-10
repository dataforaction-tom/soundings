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

"""Typed block schema for the compose_answer tool.

Single source of truth for both the Anthropic tool schema and the SSE
payload. The orchestrator validates compose_answer calls against these
models; the UI receives the same shapes via SSE.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

ComparisonBasis = Literal["percentile", "rank", "absolute", "rate"]
Severity = Literal["notable", "extreme"]

MAX_TOTAL_BLOCKS = 20
MAX_VISUAL_BLOCKS = 10

_VISUAL_TYPES = frozenset(
    {
        "indicator-card",
        "trend-chart",
        "compare-chart",
        "organisations",
        "insight-callout",
        "map",
        "distribution-chart",
        "composition-chart",
        "scatter-plot",
    }
)


class TextBlock(BaseModel):
    type: Literal["text"]
    markdown: str


class IndicatorCardBlock(BaseModel):
    type: Literal["indicator-card"]
    indicator_key: str
    place_id: str
    period: str | None = None


class TrendChartBlock(BaseModel):
    type: Literal["trend-chart"]
    indicator_key: str
    place_id: str
    caption: str | None = None


class CompareChartBlock(BaseModel):
    type: Literal["compare-chart"]
    indicator_key: str
    place_ids: list[str] = Field(min_length=2, max_length=10)
    basis: ComparisonBasis = "percentile"


class OrganisationsBlock(BaseModel):
    type: Literal["organisations"]
    place_id: str
    limit: int = 5


class InsightCalloutBlock(BaseModel):
    type: Literal["insight-callout"]
    severity: Severity
    headline: str
    indicator_key: str | None = None
    place_id: str | None = None
    evidence: str


class MapOverlay(BaseModel):
    # v1: amenity point locations only. air_quality/organisations had no point
    # data and were never implemented.
    source: Literal["amenities"]
    indicator_keys: list[str] = Field(min_length=1, max_length=6)


class MapBlock(BaseModel):
    type: Literal["map"]
    place_id: str
    indicator_key: str | None = None
    granularity: Literal["sub_areas", "peers"] = "peers"
    period: str | None = None
    caption: str | None = None
    overlay: MapOverlay | None = None


class DistributionChartBlock(BaseModel):
    type: Literal["distribution-chart"]
    indicator_key: str
    place_id: str
    caption: str | None = None


class CompositionSegment(BaseModel):
    label: str
    value: float
    colour: str | None = None


class CompositionChartBlock(BaseModel):
    type: Literal["composition-chart"]
    title: str
    segments: list[CompositionSegment]
    caption: str | None = None


class ScatterPlotBlock(BaseModel):
    type: Literal["scatter-plot"]
    x_indicator_key: str
    y_indicator_key: str
    place_id: str
    caption: str | None = None


class SubAreaEntry(BaseModel):
    place_id: str
    name: str
    value: float | None = None
    percentile: float | None = None


class SubAreaTableBlock(BaseModel):
    type: Literal["sub-area-table"]
    parent_place_id: str
    indicator_key: str
    sub_areas: list[SubAreaEntry]
    parent_value: float | None = None
    period: str | None = None
    caption: str | None = None


AnswerBlock = Annotated[
    TextBlock
    | IndicatorCardBlock
    | TrendChartBlock
    | CompareChartBlock
    | OrganisationsBlock
    | InsightCalloutBlock
    | MapBlock
    | DistributionChartBlock
    | CompositionChartBlock
    | ScatterPlotBlock
    | SubAreaTableBlock,
    Field(discriminator="type"),
]


class ComposeAnswerArgs(BaseModel):
    blocks: list[AnswerBlock]

    @model_validator(mode="after")
    def _enforce_caps(self) -> "ComposeAnswerArgs":
        # Trim rather than reject. An over-eager model emitting a few too many
        # blocks shouldn't fail the entire answer — keep every text block, drop
        # only the visual blocks past the cap, then bound the total length.
        kept: list[AnswerBlock] = []
        visual_count = 0
        for block in self.blocks:
            if block.type in _VISUAL_TYPES:
                if visual_count >= MAX_VISUAL_BLOCKS:
                    continue
                visual_count += 1
            kept.append(block)
        self.blocks = kept[:MAX_TOTAL_BLOCKS]
        return self

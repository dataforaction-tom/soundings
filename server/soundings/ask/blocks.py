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
MAX_VISUAL_BLOCKS = 6

_VISUAL_TYPES = frozenset(
    {
        "indicator-card",
        "trend-chart",
        "compare-chart",
        "organisations",
        "insight-callout",
        "map",
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


class MapBlock(BaseModel):
    type: Literal["map"]
    place_id: str
    indicator_key: str | None = None
    period: str | None = None
    caption: str | None = None


AnswerBlock = Annotated[
    TextBlock
    | IndicatorCardBlock
    | TrendChartBlock
    | CompareChartBlock
    | OrganisationsBlock
    | InsightCalloutBlock
    | MapBlock,
    Field(discriminator="type"),
]


class ComposeAnswerArgs(BaseModel):
    blocks: list[AnswerBlock]

    @model_validator(mode="after")
    def _enforce_caps(self) -> "ComposeAnswerArgs":
        if len(self.blocks) > MAX_TOTAL_BLOCKS:
            raise ValueError(f"Too many blocks: {len(self.blocks)} > {MAX_TOTAL_BLOCKS}")
        visual_count = sum(1 for b in self.blocks if b.type in _VISUAL_TYPES)
        if visual_count > MAX_VISUAL_BLOCKS:
            raise ValueError(f"Too many visual blocks: {visual_count} > {MAX_VISUAL_BLOCKS}")
        return self

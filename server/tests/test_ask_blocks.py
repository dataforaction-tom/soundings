"""Unit tests for the compose_answer block schema."""

import pytest
from pydantic import TypeAdapter, ValidationError

from soundings.ask.blocks import (
    AnswerBlock,
    CompareChartBlock,
    ComposeAnswerArgs,
    IndicatorCardBlock,
    InsightCalloutBlock,
    OrganisationsBlock,
    TextBlock,
    TrendChartBlock,
)


def test_text_block_valid():
    b = TextBlock(type="text", markdown="Hello **world**")
    assert b.type == "text"
    assert b.markdown == "Hello **world**"


def test_indicator_card_block_valid():
    b = IndicatorCardBlock(
        type="indicator-card", indicator_key="population.total", place_id="ltla24:E06000047"
    )
    assert b.indicator_key == "population.total"
    assert b.period is None


def test_trend_chart_block_with_caption():
    b = TrendChartBlock(
        type="trend-chart",
        indicator_key="population.total",
        place_id="ltla24:E06000047",
        caption="Population over time",
    )
    assert b.caption == "Population over time"


def test_compare_chart_block_defaults():
    b = CompareChartBlock(
        type="compare-chart",
        indicator_key="population.total",
        place_ids=["ltla24:E06000047", "ltla24:E08000029"],
    )
    assert b.basis == "percentile"
    assert len(b.place_ids) == 2


def test_organisations_block_defaults():
    b = OrganisationsBlock(type="organisations", place_id="ltla24:E06000047")
    assert b.limit == 5


def test_insight_callout_block():
    b = InsightCalloutBlock(
        type="insight-callout",
        severity="extreme",
        headline="Bottom 5% for life expectancy",
        evidence="Stockton's female life expectancy is in the bottom decile nationally.",
    )
    assert b.severity == "extreme"
    assert b.indicator_key is None


def test_insight_callout_rejects_bad_severity():
    with pytest.raises(ValidationError):
        InsightCalloutBlock(
            type="insight-callout",
            severity="critical",
            headline="test",
            evidence="test",
        )


def test_compose_answer_rejects_unknown_block_type():
    with pytest.raises(ValidationError):
        ComposeAnswerArgs.model_validate({"blocks": [{"type": "unknown", "data": "x"}]})


def test_compose_answer_enforces_max_blocks():
    blocks = [TextBlock(type="text", markdown=f"Block {i}") for i in range(21)]
    with pytest.raises(ValidationError):
        ComposeAnswerArgs(blocks=blocks)


def test_compose_answer_enforces_max_visual_blocks():
    visual = [
        IndicatorCardBlock(
            type="indicator-card", indicator_key=f"k{i}", place_id="ltla24:E06000047"
        )
        for i in range(7)
    ]
    text = [TextBlock(type="text", markdown="intro")]
    with pytest.raises(ValidationError):
        ComposeAnswerArgs(blocks=text + visual)


def test_compose_answer_at_limits():
    visual = [
        IndicatorCardBlock(
            type="indicator-card", indicator_key=f"k{i}", place_id="ltla24:E06000047"
        )
        for i in range(6)
    ]
    text = [TextBlock(type="text", markdown=f"Block {i}") for i in range(14)]
    args = ComposeAnswerArgs(blocks=text + visual)
    assert len(args.blocks) == 20


def test_discriminator_routes_correctly():
    _adapter = TypeAdapter(AnswerBlock)
    raw = {"type": "text", "markdown": "hi"}
    b = _adapter.validate_python(raw)
    assert isinstance(b, TextBlock)

    raw = {"type": "insight-callout", "severity": "notable", "headline": "x", "evidence": "y"}
    b = _adapter.validate_python(raw)
    assert isinstance(b, InsightCalloutBlock)

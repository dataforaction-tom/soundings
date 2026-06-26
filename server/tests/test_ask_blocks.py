"""Unit tests for the compose_answer block schema."""

import pytest
from pydantic import TypeAdapter, ValidationError

from soundings.ask.blocks import (
    AnswerBlock,
    CompareChartBlock,
    ComposeAnswerArgs,
    CompositionChartBlock,
    CompositionSegment,
    DistributionChartBlock,
    IndicatorCardBlock,
    InsightCalloutBlock,
    MapBlock,
    MapOverlay,
    OrganisationsBlock,
    ScatterPlotBlock,
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


def test_compose_answer_trims_to_max_total_blocks():
    blocks = [TextBlock(type="text", markdown=f"Block {i}") for i in range(21)]
    args = ComposeAnswerArgs(blocks=blocks)
    # Over-length answers are trimmed to the cap rather than rejected.
    assert len(args.blocks) == 20


def test_compose_answer_trims_excess_visual_blocks():
    visual = [
        IndicatorCardBlock(
            type="indicator-card", indicator_key=f"k{i}", place_id="ltla24:E06000047"
        )
        for i in range(12)
    ]
    text = [TextBlock(type="text", markdown="intro")]
    args = ComposeAnswerArgs(blocks=text + visual)
    # Excess visual blocks are dropped; text blocks are always kept.
    visual_kept = sum(1 for b in args.blocks if b.type == "indicator-card")
    assert visual_kept == 10
    assert any(b.type == "text" for b in args.blocks)


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


def test_map_block_valid():
    b = MapBlock(type="map", place_id="ltla24:E06000047")
    assert b.place_id == "ltla24:E06000047"
    assert b.indicator_key is None
    assert b.period is None
    assert b.caption is None


def test_map_block_with_choropleth():
    b = MapBlock(
        type="map",
        place_id="ltla24:E06000047",
        indicator_key="population.total",
        period="2023",
        caption="Population density across peer places",
    )
    assert b.indicator_key == "population.total"
    assert b.period == "2023"
    assert b.caption == "Population density across peer places"


def test_map_block_in_compose_answer():
    args = ComposeAnswerArgs(
        blocks=[
            TextBlock(type="text", markdown="Here is a map:"),
            MapBlock(type="map", place_id="ltla24:E06000047"),
        ]
    )
    assert len(args.blocks) == 2


def test_map_block_counts_as_visual():
    """MapBlock should count toward the visual block cap (and be trimmed)."""
    visual = [MapBlock(type="map", place_id=f"ltla24:E060000{i:02d}") for i in range(12)]
    text = [TextBlock(type="text", markdown="intro")]
    args = ComposeAnswerArgs(blocks=text + visual)
    assert sum(1 for b in args.blocks if b.type == "map") == 10


def test_map_block_discriminator():
    _adapter = TypeAdapter(AnswerBlock)
    raw = {"type": "map", "place_id": "ltla24:E06000047"}
    b = _adapter.validate_python(raw)
    assert isinstance(b, MapBlock)


def test_map_block_overlay_defaults_none():
    b = MapBlock(type="map", place_id="ltla24:E06000047")
    assert b.overlay is None


def test_map_block_with_amenities_overlay():
    b = MapBlock(
        type="map",
        place_id="ltla24:E06000047",
        overlay=MapOverlay(source="amenities", indicator_keys=["infrastructure.food_banks_count"]),
    )
    assert b.overlay is not None
    assert b.overlay.source == "amenities"
    assert b.overlay.indicator_keys == ["infrastructure.food_banks_count"]


def test_map_block_with_multiple_indicator_keys():
    b = MapBlock(
        type="map",
        place_id="ltla24:E06000047",
        overlay=MapOverlay(
            source="amenities",
            indicator_keys=["infrastructure.food_banks_count", "infrastructure.leisure_centres"],
        ),
    )
    assert b.overlay is not None
    assert len(b.overlay.indicator_keys) == 2


def test_map_overlay_rejects_bad_source():
    with pytest.raises(ValidationError):
        MapOverlay(source="unknown")  # type: ignore[arg-type]


def test_map_block_accepts_granularity_and_amenity_overlay():
    args = ComposeAnswerArgs.model_validate(
        {
            "blocks": [
                {
                    "type": "map",
                    "place_id": "ltla24:E06000047",
                    "indicator_key": "deprivation.imd.score",
                    "granularity": "sub_areas",
                },
                {
                    "type": "map",
                    "place_id": "ltla24:E06000047",
                    "overlay": {
                        "source": "amenities",
                        "indicator_keys": ["infrastructure.food_banks_count"],
                    },
                },
            ]
        }
    )
    assert args.blocks[0].granularity == "sub_areas"
    assert args.blocks[1].overlay.indicator_keys == ["infrastructure.food_banks_count"]


def test_map_block_granularity_defaults_to_peers():
    args = ComposeAnswerArgs.model_validate(
        {"blocks": [{"type": "map", "place_id": "ltla24:E06000047", "indicator_key": "x"}]}
    )
    assert args.blocks[0].granularity == "peers"


def test_amenity_overlay_rejects_empty_indicator_keys():
    with pytest.raises(ValidationError):
        ComposeAnswerArgs.model_validate(
            {
                "blocks": [
                    {
                        "type": "map",
                        "place_id": "ltla24:E06000047",
                        "overlay": {"source": "amenities", "indicator_keys": []},
                    }
                ]
            }
        )


# ---------------------------------------------------------------------------
# DistributionChartBlock
# ---------------------------------------------------------------------------


def test_distribution_chart_block_valid():
    b = DistributionChartBlock(
        type="distribution-chart",
        indicator_key="population.total",
        place_id="ltla24:E06000047",
        caption="Distribution across peer places",
    )
    assert b.indicator_key == "population.total"
    assert b.place_id == "ltla24:E06000047"
    assert b.caption == "Distribution across peer places"


def test_distribution_chart_block_optional_caption_default():
    b = DistributionChartBlock(
        type="distribution-chart",
        indicator_key="population.total",
        place_id="ltla24:E06000047",
    )
    assert b.caption is None


def test_distribution_chart_block_counts_as_visual():
    """DistributionChartBlock should count toward the visual block cap (and be trimmed)."""
    visual = [
        DistributionChartBlock(
            type="distribution-chart",
            indicator_key=f"k{i}",
            place_id="ltla24:E06000047",
        )
        for i in range(12)
    ]
    text = [TextBlock(type="text", markdown="intro")]
    args = ComposeAnswerArgs(blocks=text + visual)
    assert sum(1 for b in args.blocks if b.type == "distribution-chart") == 10
    assert any(b.type == "text" for b in args.blocks)


def test_distribution_chart_block_discriminator():
    _adapter = TypeAdapter(AnswerBlock)
    raw = {
        "type": "distribution-chart",
        "indicator_key": "population.total",
        "place_id": "ltla24:E06000047",
    }
    b = _adapter.validate_python(raw)
    assert isinstance(b, DistributionChartBlock)


# ---------------------------------------------------------------------------
# CompositionChartBlock
# ---------------------------------------------------------------------------


def test_composition_chart_block_valid():
    segments = [
        CompositionSegment(label="Public", value=60.0, colour="#4c78a8"),
        CompositionSegment(label="Private", value=40.0),
    ]
    b = CompositionChartBlock(
        type="composition-chart",
        title="Funding sources",
        segments=segments,
        caption="Breakdown of income by source",
    )
    assert b.title == "Funding sources"
    assert len(b.segments) == 2
    assert b.segments[0].label == "Public"
    assert b.segments[0].value == 60.0
    assert b.segments[0].colour == "#4c78a8"
    assert b.segments[1].colour is None
    assert b.caption == "Breakdown of income by source"


def test_composition_chart_block_optional_caption_default():
    b = CompositionChartBlock(
        type="composition-chart",
        title="Funding sources",
        segments=[CompositionSegment(label="Public", value=60.0)],
    )
    assert b.caption is None


def test_composition_chart_block_counts_as_visual():
    """CompositionChartBlock should count toward the visual block cap (and be trimmed)."""
    visual = [
        CompositionChartBlock(
            type="composition-chart",
            title=f"Chart {i}",
            segments=[CompositionSegment(label="A", value=1.0)],
        )
        for i in range(12)
    ]
    text = [TextBlock(type="text", markdown="intro")]
    args = ComposeAnswerArgs(blocks=text + visual)
    assert sum(1 for b in args.blocks if b.type == "composition-chart") == 10
    assert any(b.type == "text" for b in args.blocks)


def test_composition_chart_block_discriminator():
    _adapter = TypeAdapter(AnswerBlock)
    raw = {
        "type": "composition-chart",
        "title": "Funding sources",
        "segments": [{"label": "Public", "value": 60.0}],
    }
    b = _adapter.validate_python(raw)
    assert isinstance(b, CompositionChartBlock)
    assert isinstance(b.segments[0], CompositionSegment)


# ---------------------------------------------------------------------------
# ScatterPlotBlock
# ---------------------------------------------------------------------------


def test_scatter_plot_block_valid():
    b = ScatterPlotBlock(
        type="scatter-plot",
        x_indicator_key="income.median",
        y_indicator_key="health.expectancy",
        place_id="ltla24:E06000047",
        caption="Income vs life expectancy",
    )
    assert b.x_indicator_key == "income.median"
    assert b.y_indicator_key == "health.expectancy"
    assert b.place_id == "ltla24:E06000047"
    assert b.caption == "Income vs life expectancy"


def test_scatter_plot_block_optional_caption_default():
    b = ScatterPlotBlock(
        type="scatter-plot",
        x_indicator_key="income.median",
        y_indicator_key="health.expectancy",
        place_id="ltla24:E06000047",
    )
    assert b.caption is None


def test_scatter_plot_block_counts_as_visual():
    """ScatterPlotBlock should count toward the visual block cap (and be trimmed)."""
    visual = [
        ScatterPlotBlock(
            type="scatter-plot",
            x_indicator_key=f"x{i}",
            y_indicator_key="health.expectancy",
            place_id="ltla24:E06000047",
        )
        for i in range(12)
    ]
    text = [TextBlock(type="text", markdown="intro")]
    args = ComposeAnswerArgs(blocks=text + visual)
    assert sum(1 for b in args.blocks if b.type == "scatter-plot") == 10
    assert any(b.type == "text" for b in args.blocks)


def test_scatter_plot_block_discriminator():
    _adapter = TypeAdapter(AnswerBlock)
    raw = {
        "type": "scatter-plot",
        "x_indicator_key": "income.median",
        "y_indicator_key": "health.expectancy",
        "place_id": "ltla24:E06000047",
    }
    b = _adapter.validate_python(raw)
    assert isinstance(b, ScatterPlotBlock)

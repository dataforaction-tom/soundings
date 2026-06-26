"""Unit tests for the system prompt builder."""

import pytest

from soundings.ask.prompts import SystemPromptBuilder


def test_open_mode_prompt_contains_general_guidance():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "Soundings" in prompt
    assert "tool" in prompt.lower()
    assert "compose_answer" in prompt


def test_summary_mode_emphasises_breadth():
    builder = SystemPromptBuilder(mode="summary")
    prompt = builder.build()
    assert "breadth" in prompt.lower() or "summary" in prompt.lower()


def test_compare_mode_emphasises_comparison():
    builder = SystemPromptBuilder(mode="compare")
    prompt = builder.build()
    assert "compare" in prompt.lower()
    assert "percentile" in prompt.lower()


def test_insight_mode_emphasises_signals():
    builder = SystemPromptBuilder(mode="insight")
    prompt = builder.build()
    assert "insight" in prompt.lower() or "surprising" in prompt.lower()
    assert "detect_insights" in prompt


def test_pinned_place_included_in_prompt():
    builder = SystemPromptBuilder(
        mode="open", place_name="Stockton-on-Tees", place_id="ltla24:E06000004"
    )
    prompt = builder.build()
    assert "Stockton-on-Tees" in prompt
    assert "ltla24:E06000004" in prompt


def test_scope_guardrail_present():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "population" in prompt
    assert "health" in prompt
    assert "cannot help" in prompt.lower() or "out of scope" in prompt.lower()


def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        SystemPromptBuilder(mode="bad")  # type: ignore[arg-type]


def test_prompt_mentions_distribution_chart():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "distribution-chart" in prompt


def test_prompt_mentions_composition_chart():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "composition-chart" in prompt


def test_prompt_mentions_scatter_plot():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "scatter-plot" in prompt


def test_prompt_mentions_get_peer_distribution():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "get_peer_distribution" in prompt


def test_prompt_has_chart_selection_guidance():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "Use distribution-chart" in prompt
    assert "Use composition-chart" in prompt
    assert "Use scatter-plot" in prompt


def test_prompt_mentions_map_overlay():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "overlay" in prompt.lower()
    assert "air_quality" in prompt
    assert "organisations" in prompt
    assert "amenities" in prompt


def test_prompt_mentions_environment_domain():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "environment" in prompt.lower()


def test_prompt_mentions_air_quality():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "air quality" in prompt.lower()


def test_prompt_notes_air_quality_is_point_sensor_data():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "point-sensor" in prompt.lower() or "point sensor" in prompt.lower()
    assert "interpolat" in prompt.lower()


def test_prompt_mentions_infrastructure_domain():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "infrastructure" in prompt.lower()


def test_prompt_mentions_osm_amenity_counts():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "amenity" in prompt.lower() or "amenities" in prompt.lower()
    assert "openstreetmap" in prompt.lower() or "osm" in prompt.lower()

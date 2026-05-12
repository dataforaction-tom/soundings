"""Spec tests for the get_trend tool — Pydantic round-trip + defaults."""

from soundings.tools.get_trend import GetTrendInput, GetTrendOutput, tool_spec


def test_input_minimal_round_trips() -> None:
    input = GetTrendInput(place_id="ltla24:E06000004", indicator="population.total")
    restored = GetTrendInput.model_validate(input.model_dump())
    assert restored == input
    assert input.period_from is None
    assert input.period_to is None


def test_input_with_window_round_trips() -> None:
    input = GetTrendInput(
        place_id="ltla24:E06000004",
        indicator="economy.employment_rate",
        period_from="Apr 2020-Mar 2021",
        period_to="Apr 2023-Mar 2024",
    )
    restored = GetTrendInput.model_validate(input.model_dump())
    assert restored == input


def test_output_round_trips_empty() -> None:
    output = GetTrendOutput()
    restored = GetTrendOutput.model_validate(output.model_dump())
    assert restored.trend is None
    assert restored.caveats == []
    assert restored.sources == []
    assert restored.partial is False


def test_tool_spec_advertises_name_and_schemas() -> None:
    spec = tool_spec()
    assert spec["name"] == "get_trend"
    assert isinstance(spec["description"], str)
    assert "input_schema" in spec
    assert "output_schema" in spec

"""Spec tests for the compare_places tool — Pydantic round-trip + defaults."""

from soundings.tools.compare_places import (
    ComparePlacesInput,
    ComparePlacesOutput,
    tool_spec,
)


def test_input_defaults_basis_to_percentile() -> None:
    """Spec §4.4 leaves `comparison_basis` optional with no default. This
    plan ships percentile as the default because "how does my place
    compare" is the most useful framing. Test pins that choice."""
    input = ComparePlacesInput(place_ids=["ltla24:E06000004"], indicators=["population.total"])
    assert input.comparison_basis == "percentile"


def test_input_accepts_explicit_basis() -> None:
    for basis in ["percentile", "rank", "absolute", "rate"]:
        input = ComparePlacesInput(
            place_ids=["ltla24:E06000004"],
            indicators=["population.total"],
            comparison_basis=basis,  # type: ignore[arg-type]
        )
        assert input.comparison_basis == basis


def test_input_round_trips_through_model_dump() -> None:
    input = ComparePlacesInput(
        place_ids=["ltla24:E06000004", "ltla24:E06000005"],
        indicators=["population.total", "deprivation.imd.score"],
        comparison_basis="rank",
    )
    restored = ComparePlacesInput.model_validate(input.model_dump())
    assert restored == input


def test_output_round_trips_empty() -> None:
    output = ComparePlacesOutput()
    restored = ComparePlacesOutput.model_validate(output.model_dump())
    assert restored.results == []
    assert restored.sources == []
    assert restored.caveats == []
    assert restored.partial is False


def test_tool_spec_advertises_name_and_schemas() -> None:
    spec = tool_spec()
    assert spec["name"] == "compare_places"
    assert isinstance(spec["description"], str)
    assert "input_schema" in spec
    assert "output_schema" in spec

"""Tests for the get_sub_areas tool."""

from soundings.tools.get_sub_areas import (
    GetSubAreasInput,
    GetSubAreasOutput,
    SubAreaValue,
    tool_spec,
)


def test_tool_spec_has_correct_name() -> None:
    spec = tool_spec()
    assert spec["name"] == "get_sub_areas"


def test_input_model_requires_place_id_and_indicator() -> None:
    model = GetSubAreasInput(place_id="ltla24:E06000004", indicator_key="deprivation.imd.score")
    assert model.place_id == "ltla24:E06000004"
    assert model.indicator_key == "deprivation.imd.score"
    assert model.child_type == "lsoa21"  # default


def test_output_model_has_sub_areas_list() -> None:
    out = GetSubAreasOutput(
        parent_place_id="ltla24:E06000004",
        indicator_key="deprivation.imd.score",
        child_type="lsoa21",
        sub_areas=[
            SubAreaValue(
                place_id="lsoa21:E01001234",
                name="Stockton 001A",
                value=32.5,
                percentile=85.0,
            ),
        ],
        parent_value=22.0,
        parent_percentile=55.0,
        period="2025",
    )
    assert len(out.sub_areas) == 1
    assert out.sub_areas[0].value == 32.5

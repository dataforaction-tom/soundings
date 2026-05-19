"""Tests for find_organisations_in_place tool spec."""

import pytest

from soundings.tools.find_organisations_in_place import (
    FindOrganisationsInPlaceInput,
    FindOrganisationsInPlaceOutput,
    TOOL_NAME,
    TOOL_DESCRIPTION,
    tool_spec,
)


def test_tool_spec_has_expected_fields():
    spec = tool_spec()
    assert spec["name"] == TOOL_NAME
    assert spec["description"] == TOOL_DESCRIPTION
    assert "input_schema" in spec
    assert "output_schema" in spec


def test_input_schema_validates_required_fields():
    inp = FindOrganisationsInPlaceInput(place_id="ltla24:E06000004")
    assert inp.place_id == "ltla24:E06000004"
    assert inp.activity_filter is None
    assert inp.funded_only is False
    assert inp.limit == 50


def test_input_schema_accepts_optional_fields():
    inp = FindOrganisationsInPlaceInput(
        place_id="ltla24:S12000033",
        activity_filter=["health", "education"],
        funded_only=True,
        limit=25,
    )
    assert inp.place_id == "ltla24:S12000033"
    assert inp.activity_filter == ["health", "education"]
    assert inp.funded_only is True
    assert inp.limit == 25


def test_output_schema_default_values():
    out = FindOrganisationsInPlaceOutput()
    assert out.organisations == []
    assert out.sources == []
    assert out.caveats == []
    assert out.partial is False


def test_input_json_schema_has_descriptions():
    schema = FindOrganisationsInPlaceInput.model_json_schema()
    # Check that descriptions are present
    assert "place_id" in schema["properties"]
    assert "description" in schema["properties"]["place_id"]
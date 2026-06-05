"""Tests for get_civil_society_profile tool spec."""

import pytest
from pydantic import ValidationError

from soundings.tools.get_civil_society_profile import (
    TOOL_DESCRIPTION,
    TOOL_NAME,
    GetCivilSocietyProfileInput,
    tool_spec,
)


def test_tool_spec_has_expected_fields() -> None:
    spec = tool_spec()
    assert spec["name"] == TOOL_NAME
    assert spec["description"] == TOOL_DESCRIPTION
    assert "input_schema" in spec
    assert "output_schema" in spec


def test_input_validation_accepts_place_id() -> None:
    parsed = GetCivilSocietyProfileInput(place_id="ltla24:E06000047")
    assert parsed.place_id == "ltla24:E06000047"


def test_input_validation_rejects_missing_place_id() -> None:
    with pytest.raises(ValidationError):
        GetCivilSocietyProfileInput.model_validate({})

from soundings.tools.find_place import tool_spec as find_place_spec


def test_find_place_tool_spec_shape() -> None:
    spec = find_place_spec()
    assert spec["name"] == "find_place"
    assert "description" in spec
    assert spec["input_schema"]["properties"].keys() >= {"query", "geography_types"}
    assert "matches" in spec["output_schema"]["properties"]

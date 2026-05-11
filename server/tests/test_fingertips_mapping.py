from soundings.adapters.ohid_fingertips.mapping import (
    DEFAULT_MAPPING_PATH,
    load_fingertips_mapping,
)


def test_default_mapping_file_exists() -> None:
    assert DEFAULT_MAPPING_PATH.exists()


def test_mapping_loads_and_covers_known_indicators() -> None:
    mappings = load_fingertips_mapping()
    keys = {m.indicator_key for m in mappings}
    assert "health.life_expectancy.female" in keys
    assert "health.healthy_life_expectancy.female" in keys


def test_mapping_entries_carry_indicator_id_and_area_type() -> None:
    mappings = load_fingertips_mapping()
    by_key = {m.indicator_key: m for m in mappings}
    le_female = by_key["health.life_expectancy.female"]
    assert le_female.indicator_id == 90366
    assert le_female.child_area_type_id == 102
    assert le_female.place_type == "ltla24"
    assert le_female.sex == "Female"

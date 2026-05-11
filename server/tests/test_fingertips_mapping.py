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


def test_mapping_entries_carry_profile_group_and_sex() -> None:
    mappings = load_fingertips_mapping()
    by_key = {m.indicator_key: m for m in mappings}
    le_female = by_key["health.life_expectancy.female"]
    assert le_female.profile_id == 19
    assert le_female.group_id == 1000049
    assert le_female.indicator_id == 90366
    assert le_female.sex_id == 2
    assert le_female.age_id == 1
    assert le_female.child_area_type_id == 501
    assert le_female.place_type == "ltla24"
    assert le_female.parent_area_code == "E92000001"


def test_male_and_female_share_indicator_id_but_differ_in_sex_id() -> None:
    mappings = load_fingertips_mapping()
    by_key = {m.indicator_key: m for m in mappings}
    le_m = by_key["health.life_expectancy.male"]
    le_f = by_key["health.life_expectancy.female"]
    assert le_m.indicator_id == le_f.indicator_id == 90366
    assert le_m.sex_id == 1
    assert le_f.sex_id == 2

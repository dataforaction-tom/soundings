from soundings.adapters.dfe_explore.mapping import DEFAULT_MAPPING_PATH, load_dfe_mapping


def test_default_mapping_file_exists() -> None:
    assert DEFAULT_MAPPING_PATH.exists()


def test_mapping_loads_and_covers_catalogue_dfe_indicators() -> None:
    mappings = load_dfe_mapping()
    keys = {m.indicator_key for m in mappings}
    assert "education.fsm_eligibility_share" in keys
    assert "education.ks4_attainment_8" in keys
    assert "education.persistent_absence_share" in keys


def test_fsm_entry_carries_dataset_and_indicator_ids() -> None:
    mappings = load_dfe_mapping()
    by_key = {m.indicator_key: m for m in mappings}
    fsm = by_key["education.fsm_eligibility_share"]
    # Real UUID for the LA - Free school meals dataset.
    assert fsm.data_set_id == "b79e17fb-82b1-4bcc-a295-a7ceea23e34a"
    assert fsm.indicator_id  # may be placeholder until Task 20 iterates
    assert fsm.location_level == "LA"
    assert fsm.time_period_code == "AY"
    assert fsm.place_type == "ltla24"
    assert fsm.unit == "proportion"

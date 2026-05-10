from datetime import UTC, datetime

import pytest

from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.source_ref import SourceRef


def _sample_source_ref() -> SourceRef:
    return SourceRef(
        source_id="ons.census2021",
        source_label="ONS Census 2021",
        publisher="Office for National Statistics",
        publisher_url="https://www.ons.gov.uk/census",
        dataset_url="https://www.nomisweb.co.uk/",
        retrieved_at=datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC),
        cache_status="cached",
        licence="OGL-UK-3.0",
    )


def test_source_ref_round_trips_through_json() -> None:
    src = _sample_source_ref()
    rebuilt = SourceRef.model_validate_json(src.model_dump_json())
    assert rebuilt == src
    assert rebuilt.retrieved_at.tzinfo is not None


def test_indicator_value_round_trips_with_nested_source_ref() -> None:
    iv = IndicatorValue(
        place_id="ltla24:E06000004",
        indicator="population.households.lone_parent_share",
        value=0.123,
        unit="proportion",
        period="2021",
        source=_sample_source_ref(),
        methodology_note="Census 2021, table TS003",
        caveats=["England + Wales only at LSOA/MSOA"],
        confidence="official",
    )
    rebuilt = IndicatorValue.model_validate_json(iv.model_dump_json())
    assert rebuilt == iv
    assert rebuilt.source.source_id == "ons.census2021"


def test_indicator_value_value_can_be_null() -> None:
    iv = IndicatorValue(
        place_id="ltla24:E06000004",
        indicator="population.total",
        value=None,
        unit="people",
        period="2024",
        source=_sample_source_ref(),
        confidence="official",
    )
    assert iv.value is None


def test_confidence_is_constrained() -> None:
    with pytest.raises(ValueError):
        IndicatorValue(
            place_id="x",
            indicator="y",
            value=1,
            unit="u",
            period="p",
            source=_sample_source_ref(),
            confidence="experiential",  # reserved for v3, not allowed in v1
        )

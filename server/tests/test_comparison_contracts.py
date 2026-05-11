from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from soundings.contracts.comparison import Comparison, ComparisonValue
from soundings.contracts.source_ref import SourceRef


def _source_ref() -> SourceRef:
    return SourceRef(
        source_id="ons.mid_year_estimates",
        source_label="ONS Mid-Year Estimates",
        publisher="Office for National Statistics",
        publisher_url="https://www.ons.gov.uk/",
        dataset_url="https://www.nomisweb.co.uk/",
        retrieved_at=datetime(2026, 5, 11, 10, 0, tzinfo=UTC),
        cache_status="cached",
        licence="OGL-UK-3.0",
    )


def test_comparison_round_trips_with_rank_and_percentile() -> None:
    comparison = Comparison(
        indicator="population.total",
        unit="persons",
        period="2024",
        values=[
            ComparisonValue(place_id="ltla24:E06000004", value=206800, rank=120, percentile=0.62),
            ComparisonValue(place_id="ltla24:E08000001", value=512000, rank=15, percentile=0.95),
        ],
        source=_source_ref(),
        methodology_note="Percentile against all ltla24 places.",
        caveats=["Mid-year estimates are revised after each Census."],
    )
    rehydrated = Comparison.model_validate_json(comparison.model_dump_json())
    assert rehydrated == comparison
    assert rehydrated.values[1].percentile == 0.95


def test_comparison_value_optional_rank_and_percentile() -> None:
    # basis="absolute" → no rank/percentile attached
    cv = ComparisonValue(place_id="ltla24:E06000004", value=206800)
    assert cv.rank is None
    assert cv.percentile is None


def test_comparison_value_value_can_be_null() -> None:
    cv = ComparisonValue(place_id="ltla24:E06000004", value=None)
    assert cv.value is None


def test_comparison_requires_core_fields() -> None:
    with pytest.raises(ValidationError):
        Comparison.model_validate({})  # type: ignore[arg-type]


def test_comparison_default_caveats_is_empty_list() -> None:
    comparison = Comparison(
        indicator="population.total",
        unit="persons",
        period="2024",
        values=[],
        source=_source_ref(),
    )
    assert comparison.caveats == []
    assert comparison.methodology_note is None

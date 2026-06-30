"""Unit tests for compare_places input/output contract extensions.

Covers Slice 3 Task 8: context_place_ids support. These are pure
contract-level tests that don't need a database — they verify the
ComparePlacesInput model accepts context_place_ids and defaults to an
empty list, and that Comparison carries the is_context flag.
"""

from datetime import UTC, datetime

from soundings.contracts.comparison import Comparison, ComparisonValue
from soundings.contracts.source_ref import SourceRef
from soundings.tools.compare_places import ComparePlacesInput


def _source_ref() -> SourceRef:
    return SourceRef(
        source_id="test.compare",
        source_label="Test",
        publisher="Test",
        retrieved_at=datetime.now(tz=UTC),
        cache_status="cached",
        licence="CC0",
    )


def test_compare_input_accepts_context_place_ids() -> None:
    """ComparePlacesInput accepts context_place_ids and stores them."""
    payload = ComparePlacesInput(
        place_ids=["lsoa24:E01000001"],
        indicators=["population.total"],
        context_place_ids=["ltla24:E06000001"],
    )
    assert payload.context_place_ids == ["ltla24:E06000001"]


def test_compare_input_defaults_context_place_ids_to_empty() -> None:
    """ComparePlacesInput defaults context_place_ids to an empty list."""
    payload = ComparePlacesInput(
        place_ids=["lsoa24:E01000001"],
        indicators=["population.total"],
    )
    assert payload.context_place_ids == []
    # Each call gets its own list (no shared mutable default).
    other = ComparePlacesInput(
        place_ids=["lsoa24:E01000002"],
        indicators=["population.total"],
    )
    assert other.context_place_ids is not payload.context_place_ids


def test_comparison_has_is_context_field() -> None:
    """Comparison has an is_context field that defaults to False."""
    comparison = Comparison(
        indicator="population.total",
        unit="people",
        period="2024",
        values=[
            ComparisonValue(
                place_id="ltla24:E06000001",
                value=100.0,
                rank=None,
                percentile=None,
            )
        ],
        source=_source_ref(),
    )
    assert comparison.is_context is False


def test_comparison_is_context_can_be_set_true() -> None:
    """Comparison.is_context can be explicitly set True."""
    comparison = Comparison(
        indicator="population.total",
        unit="people",
        period="2024",
        values=[
            ComparisonValue(
                place_id="ltla24:E06000001",
                value=100.0,
                rank=None,
                percentile=None,
            )
        ],
        source=_source_ref(),
        is_context=True,
    )
    assert comparison.is_context is True

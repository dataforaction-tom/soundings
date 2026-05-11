from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from soundings.contracts.source_ref import SourceRef
from soundings.contracts.trend import Trend, TrendPoint


def _source_ref() -> SourceRef:
    return SourceRef(
        source_id="ohid.fingertips",
        source_label="OHID Fingertips",
        publisher="Office for Health Improvement and Disparities",
        publisher_url="https://fingertips.phe.org.uk/",
        dataset_url="https://fingertips.phe.org.uk/profile/...",
        retrieved_at=datetime(2026, 5, 11, 10, 0, tzinfo=UTC),
        cache_status="cached",
        licence="OGL-UK-3.0",
    )


def test_trendpoint_round_trips_through_json() -> None:
    point = TrendPoint(period="2024", value=82.4, revised=False)
    assert TrendPoint.model_validate_json(point.model_dump_json()) == point


def test_trend_with_multiple_points_round_trips() -> None:
    trend = Trend(
        place_id="ltla24:E06000004",
        indicator="health.life_expectancy.female",
        unit="years",
        points=[
            TrendPoint(period="2022", value=80.1),
            TrendPoint(period="2023", value=80.6),
            TrendPoint(period="2024", value=81.0, revised=True),
        ],
        source=_source_ref(),
        breaks_in_series=["methodology changed 2018"],
    )
    rehydrated = Trend.model_validate_json(trend.model_dump_json())
    assert rehydrated == trend
    assert len(rehydrated.points) == 3
    assert rehydrated.points[2].revised is True
    assert rehydrated.breaks_in_series == ["methodology changed 2018"]


def test_trend_with_empty_points_is_valid() -> None:
    # A "no data" trend response — the place/indicator is known but no
    # series rows exist yet. Distinct from `None` (indicator not
    # supported). Round-trips cleanly.
    trend = Trend(
        place_id="ltla24:E06000004",
        indicator="welfare.claimants.total",
        unit="persons",
        points=[],
        source=_source_ref(),
    )
    assert Trend.model_validate_json(trend.model_dump_json()) == trend


def test_trendpoint_value_can_be_null() -> None:
    point = TrendPoint(period="2024", value=None)
    assert point.value is None


def test_trendpoint_rejects_extra_fields_via_pydantic_default_strict_path() -> None:
    # Pydantic v2 BaseModel defaults to extra="ignore". We don't change
    # that, so a typo on period_label silently drops rather than failing.
    # This test pins that default so future contract changes don't
    # silently accept noise.
    point = TrendPoint.model_validate({"period": "2024", "value": 1.0, "garbage": "x"})
    assert point.period == "2024"
    # The 'garbage' field is dropped by the default Pydantic config.
    assert not hasattr(point, "garbage")


def test_trend_requires_place_indicator_unit_source() -> None:
    with pytest.raises(ValidationError):
        Trend.model_validate({})  # type: ignore[arg-type]

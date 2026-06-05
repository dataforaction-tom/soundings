"""Sync helper tests for the Charity Commission client."""

from soundings.adapters.charity_commission.client import _coerce_float


def test_coerce_float_rejects_nan_and_inf() -> None:
    """_coerce_float must reject NaN and Inf to prevent SQL aggregate failures."""
    assert _coerce_float("nan") is None
    assert _coerce_float("inf") is None
    assert _coerce_float("-inf") is None
    assert _coerce_float("  ") is None
    assert _coerce_float("not a number") is None
    assert _coerce_float("150000") == 150000.0
    assert _coerce_float(None) is None
    # Negative incomes are data anomalies — CC gross income can't be negative.
    assert _coerce_float("-5000") is None
    assert _coerce_float("-0.01") is None
    # Zero is a legitimate value (e.g., dormant charities).
    assert _coerce_float("0") == 0.0

"""ons.mid_year_estimates adapter.

The loader IS the adapter — `load()` populates `data.indicator_value` on
schedule, and `fetch_indicator` (inherited from `LoaderAdapter`) reads from
that same table when a tool asks for a value. This module re-exports under
the canonical "Adapter" name so callers don't need to know the loader path.
"""

from soundings.adapters.ons_mid_year_estimates.loader import OnsMidYearEstimatesLoader

OnsMidYearEstimatesAdapter = OnsMidYearEstimatesLoader

__all__ = ["OnsMidYearEstimatesAdapter"]

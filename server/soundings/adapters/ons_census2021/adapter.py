"""ons.census2021 adapter.

Same pattern as ons.mid_year_estimates — the loader IS the adapter, and the
default `fetch_indicator` from `LoaderAdapter` reads from
`data.indicator_value`.
"""

from soundings.adapters.ons_census2021.loader import OnsCensus2021Loader

OnsCensus2021Adapter = OnsCensus2021Loader

__all__ = ["OnsCensus2021Adapter"]

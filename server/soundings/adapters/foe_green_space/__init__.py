"""FoE green-space adapter.

The loader doubles as the read adapter (loader-mode `fetch_indicator`
comes from `LoaderAdapter`), aliased to match the Phase 1 naming pattern
(`OnsMidYearEstimatesAdapter`, `MhclgImd2025Adapter`, etc.).
"""

from soundings.adapters.foe_green_space.loader import FoeGreenSpaceLoader

FoeGreenSpaceAdapter = FoeGreenSpaceLoader

__all__ = ["FoeGreenSpaceAdapter", "FoeGreenSpaceLoader"]

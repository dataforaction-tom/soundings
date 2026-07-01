"""Companies House adapter.

The loader doubles as the read adapter (loader-mode `fetch_indicator`
comes from `LoaderAdapter`), aliased to match the Phase 1 naming pattern.
"""

from soundings.adapters.companies_house.loader import CompaniesHouseLoader

CompaniesHouseAdapter = CompaniesHouseLoader

__all__ = ["CompaniesHouseAdapter", "CompaniesHouseLoader"]

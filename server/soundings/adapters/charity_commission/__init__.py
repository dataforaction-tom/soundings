"""Charity Commission for England and Wales — loader-mode adapter.

Re-exports `CharityCommissionLoader` under the canonical
`CharityCommissionAdapter` name to match the Phase 1 pattern
(`OnsMidYearEstimatesAdapter`, `MhclgImd2025Adapter` etc.).
"""

from soundings.adapters.charity_commission.loader import CharityCommissionLoader

CharityCommissionAdapter = CharityCommissionLoader

__all__ = ["CharityCommissionAdapter", "CharityCommissionLoader"]

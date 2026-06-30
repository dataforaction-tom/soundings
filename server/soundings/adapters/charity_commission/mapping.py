"""CC postcode → LTLA resolution.

The resolver now lives in the shared `adapters.postcodes_io.resolver`
module (a second consumer — the Companies House loader — joined the
Charity Commission loader). Re-exported here for backwards
compatibility with existing CC imports.
"""

from soundings.adapters.postcodes_io.resolver import resolve_postcodes_to_ltlas

__all__ = ["resolve_postcodes_to_ltlas"]

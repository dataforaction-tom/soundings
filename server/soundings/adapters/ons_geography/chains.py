"""LookupChain configurations for the OGP hierarchy loader.

URLs and field names mirror ADR-0001 §Lookups. Treat any `(unverified)`
entry as needing a sanity-check at first run.
"""

from soundings.adapters.ons_geography.hierarchy_loader import LookupChain

OGP_LOOKUP_HOST = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"

# Postcode → OA → LSOA → MSOA → LAD lookup, Feb 2025 edition.
# We use the OA-free chain: LSOA → MSOA → LTLA. (unverified service name)
LSOA_MSOA_LTLA = LookupChain(
    url=f"{OGP_LOOKUP_HOST}/PCD_OA21_LSOA21_MSOA21_LAD_FEB25_UK_LU/FeatureServer/0",
    levels=[
        ("lsoa21", "LSOA21CD"),
        ("msoa21", "MSOA21CD"),
        ("ltla24", "LAD24CD"),
    ],
)

# LTLA → UTLA → Region → Country chain. Sourced from the LAD → CTY → RGN
# → CTRY lookup. (unverified service name)
LTLA_UTLA_REGION_COUNTRY = LookupChain(
    url=f"{OGP_LOOKUP_HOST}/LAD24_CTY24_RGN24_CTRY24_UK_LU/FeatureServer/0",
    levels=[
        ("ltla24", "LAD24CD"),
        ("utla24", "CTYUA24CD"),
        ("region", "RGN24CD"),
        ("country", "CTRY24CD"),
    ],
)

# Westminster Constituency → LTLA lookup, July 2024. (unverified service name)
WCONS_LTLA = LookupChain(
    url=f"{OGP_LOOKUP_HOST}/PCON_JUL24_LAD24_UK_LU/FeatureServer/0",
    levels=[
        ("westminster_constituency_24", "PCON24CD"),
        ("ltla24", "LAD24CD"),
    ],
)

# Ward → LTLA → UTLA → Westminster constituency lookup, July 2024. (unverified)
WARD_LTLA_UTLA = LookupChain(
    url=f"{OGP_LOOKUP_HOST}/WD24_LAD24_CTY24_PCON24_UK_LU/FeatureServer/0",
    levels=[
        ("ward24", "WD24CD"),
        ("ltla24", "LAD24CD"),
        ("utla24", "CTYUA24CD"),
        ("westminster_constituency_24", "PCON24CD"),
    ],
)


ALL_CHAINS = [
    LSOA_MSOA_LTLA,
    LTLA_UTLA_REGION_COUNTRY,
    WCONS_LTLA,
    WARD_LTLA_UTLA,
]

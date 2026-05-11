"""build_default_pipeline — assemble the full six-rule sanitisation pipeline.

Loads:
- LSOA/MSOA names from `geography.place` for StripFineGeographyInFreeText
- Small-org names from `data.organisation` (Phase 4 will populate)
- Loads spaCy `en_core_web_sm` via StripPersonalNamesViaNER constructor

Lives in `app.py`'s lifespan so the production server gets the full
rule set; tests can call it directly.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.capture.sanitisation.config import SanitisationConfig
from soundings.capture.sanitisation.direct_identifiers import StripDirectIdentifiers
from soundings.capture.sanitisation.fine_geography import StripFineGeographyInFreeText
from soundings.capture.sanitisation.normalise import (
    NormaliseAskerPurpose,
    ValidateConsentLevel,
)
from soundings.capture.sanitisation.personal_names import StripPersonalNamesViaNER
from soundings.capture.sanitisation.pipeline import SanitisationPipeline
from soundings.capture.sanitisation.small_orgs import StripSmallOrgNames


async def _load_fine_place_names(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT name FROM geography.place "
                    "WHERE type IN ('lsoa21', 'msoa21') AND name IS NOT NULL"
                )
            )
        ).all()
    return [row.name for row in rows]


async def _load_small_org_names(engine: AsyncEngine, threshold_gbp: int) -> list[str]:
    """Phase 4 populates data.organisation with income data; until then the
    table is empty (or lacks income info) and this returns an empty list."""
    # data.organisation doesn't carry an income column yet — Phase 4 adds
    # one alongside the Charity Commission seeder. For Phase 3 we
    # gracefully return [] so the rule is a no-op in production.
    del engine, threshold_gbp
    return []


async def build_default_pipeline(
    engine: AsyncEngine, config: SanitisationConfig
) -> SanitisationPipeline:
    fine_place_names = await _load_fine_place_names(engine)
    small_org_names = await _load_small_org_names(engine, config.small_org.income_threshold_gbp)
    return SanitisationPipeline(
        rules=[
            StripDirectIdentifiers(),
            StripFineGeographyInFreeText(fine_place_names=fine_place_names),
            StripPersonalNamesViaNER(),
            StripSmallOrgNames(small_org_names=small_org_names),
            NormaliseAskerPurpose(),
            ValidateConsentLevel(),
        ]
    )

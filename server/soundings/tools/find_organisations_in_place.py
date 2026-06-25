"""find_organisations_in_place tool — resolve organisations operating in a place.

Per spec §4.6. Mixed-mode dispatch:
- England/Wales → SELECT from data.organisation (CC loader-populated)
- Scotland/NI → FTC passthrough adapter
- Optional 360G grant enrichment for recent grants.
"""

from typing import Any

from pydantic import BaseModel, Field

from soundings.contracts.organisation import OrganisationRef
from soundings.contracts.source_ref import SourceRef


class FindOrganisationsInPlaceInput(BaseModel):
    place_id: str = Field(description="Canonical geography place ID (e.g. ltla24:E06000004)")
    activity_filter: list[str] | None = Field(
        default=None,
        description="Filter by activity classification codes (currently ignored in v1)",
    )
    funded_only: bool = Field(
        default=False,
        description=(
            "Only return organisations that have received grants (requires data.grant_record)"
        ),
    )
    limit: int = Field(
        default=50,
        description="Maximum number of organisations to return",
    )


class FindOrganisationsInPlaceOutput(BaseModel):
    organisations: list[OrganisationRef] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    partial: bool = Field(default=False, description="True if any leg of the query failed")


TOOL_NAME = "find_organisations_in_place"
TOOL_DESCRIPTION = (
    "Find organisations (charities, nonprofits) operating in a given UK place. "
    "For England/Wales returns Charity Commission data; for Scotland/NI queries "
    "Find That Charity. Optionally enriches with recent grant data from 360Giving."
)


def tool_spec() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": FindOrganisationsInPlaceInput.model_json_schema(),
        "output_schema": FindOrganisationsInPlaceOutput.model_json_schema(),
    }


async def find_organisations_in_place(
    input: FindOrganisationsInPlaceInput,
    orchestrator: Any,
) -> FindOrganisationsInPlaceOutput:
    """Tool handler - calls orchestrator method and wraps result.

    Grant enrichment is intentionally disabled: it fans out a live 360Giving
    call per organisation (tens of seconds for a typical place), which blows
    past the request-time budget and doesn't scale across thousands of orgs.
    Populating grants needs the 360G bulk loader (a separate slice); until
    then this tool returns the organisation list only, fast, and the aggregate
    funding picture is available via `get_civil_society_profile`.
    """
    result = await orchestrator.find_organisations_in_place(
        place_id=input.place_id,
        activity_filter=input.activity_filter,
        funded_only=input.funded_only,
        limit=input.limit,
        enrich_grants=False,
    )
    caveats = list(result.caveats)
    caveats.append(
        "Per-organisation grant detail is not included here; "
        "use get_civil_society_profile for the area's funding picture."
    )
    return FindOrganisationsInPlaceOutput(
        organisations=result.organisations,
        sources=result.sources,
        caveats=caveats,
        partial=result.partial,
    )

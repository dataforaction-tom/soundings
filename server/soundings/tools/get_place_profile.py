"""get_place_profile tool — baseline summary of a place per spec §4.2.

Resolves `include` domains to indicator keys via catalogue prefix match,
then fans out via the orchestrator. Per-domain failures become caveats,
not errors.
"""

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.source_ref import SourceRef
from soundings.orchestration.errors import GeographyNotFoundError
from soundings.orchestration.orchestrator import IndicatorOrchestrator


class PlaceHeader(BaseModel):
    id: str
    name: str
    type: str


class GetPlaceProfileInput(BaseModel):
    place_id: str
    include: list[str] = Field(default_factory=list)


class GetPlaceProfileOutput(BaseModel):
    place: PlaceHeader
    indicators: list[IndicatorValue] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    partial: bool = False


async def get_place_profile(
    input: GetPlaceProfileInput,
    orchestrator: IndicatorOrchestrator,
    engine: AsyncEngine,
) -> GetPlaceProfileOutput:
    header = await _resolve_place_header(engine, input.place_id)
    indicator_keys = await _resolve_indicators(engine, input.include)
    result = await orchestrator.fetch(
        indicator_keys=indicator_keys,
        place_id=input.place_id,
        period=None,
    )
    return GetPlaceProfileOutput(
        place=header,
        indicators=result.values,
        sources=result.sources,
        caveats=result.caveats,
        partial=result.partial,
    )


async def _resolve_place_header(engine: AsyncEngine, place_id: str) -> PlaceHeader:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, name, type FROM geography.place WHERE id = :id"
                ),
                {"id": place_id},
            )
        ).first()
    if row is None:
        raise GeographyNotFoundError(place_id)
    return PlaceHeader(id=row.id, name=row.name, type=row.type)


async def _resolve_indicators(engine: AsyncEngine, domains: list[str]) -> list[str]:
    if not domains:
        # Default: all top-level domains in the catalogue.
        async with engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT key FROM catalogue.indicator"))
            ).all()
        return [r.key for r in rows]

    like_patterns = [f"{d}.%" for d in domains]
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT key FROM catalogue.indicator "
                    "WHERE key LIKE ANY(:patterns) OR key = ANY(:exact)"
                ),
                {"patterns": like_patterns, "exact": list(domains)},
            )
        ).all()
    return [r.key for r in rows]


TOOL_NAME = "get_place_profile"
TOOL_DESCRIPTION = (
    "Baseline summary of a place: returns the indicators in the requested "
    "domains, with provenance and caveats."
)


def tool_spec() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": GetPlaceProfileInput.model_json_schema(),
        "output_schema": GetPlaceProfileOutput.model_json_schema(),
    }

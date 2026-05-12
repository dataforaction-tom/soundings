"""HTTP routes for the three Phase 1 tools.

Mounted under `/v1/tools/...`. Each route validates input against the tool's
Pydantic model and returns the tool's output Pydantic. The same tool
implementations are also registered with the MCP server at `/mcp`.
"""

from fastapi import APIRouter, Request

from soundings.tools.compare_places import (
    ComparePlacesInput,
    ComparePlacesOutput,
    compare_places,
)
from soundings.tools.compare_places import tool_spec as compare_places_spec
from soundings.tools.find_place import (
    FindPlaceInput,
    FindPlaceOutput,
    find_place,
)
from soundings.tools.find_place import tool_spec as find_place_spec
from soundings.tools.get_indicators import (
    GetIndicatorsInput,
    GetIndicatorsOutput,
    get_indicators,
)
from soundings.tools.get_indicators import tool_spec as get_indicators_spec
from soundings.tools.get_place_profile import (
    GetPlaceProfileInput,
    GetPlaceProfileOutput,
    get_place_profile,
)
from soundings.tools.get_place_profile import tool_spec as get_place_profile_spec
from soundings.tools.get_trend import (
    GetTrendInput,
    GetTrendOutput,
    get_trend,
)
from soundings.tools.get_trend import tool_spec as get_trend_spec

router = APIRouter(prefix="/v1/tools")


@router.get("")
async def list_tools() -> dict[str, list[dict[str, object]]]:
    return {
        "tools": [
            find_place_spec(),
            get_indicators_spec(),
            get_place_profile_spec(),
            compare_places_spec(),
            get_trend_spec(),
        ]
    }


@router.post("/find_place", response_model=FindPlaceOutput)
async def http_find_place(input: FindPlaceInput, request: Request) -> FindPlaceOutput:
    return await find_place(input, request.app.state.geography_service)


@router.post("/get_indicators", response_model=GetIndicatorsOutput)
async def http_get_indicators(input: GetIndicatorsInput, request: Request) -> GetIndicatorsOutput:
    return await get_indicators(input, request.app.state.orchestrator)


@router.post("/get_place_profile", response_model=GetPlaceProfileOutput)
async def http_get_place_profile(
    input: GetPlaceProfileInput, request: Request
) -> GetPlaceProfileOutput:
    return await get_place_profile(
        input,
        request.app.state.orchestrator,
        request.app.state.engine,
    )


@router.post("/compare_places", response_model=ComparePlacesOutput)
async def http_compare_places(input: ComparePlacesInput, request: Request) -> ComparePlacesOutput:
    return await compare_places(input, request.app.state.orchestrator)


@router.post("/get_trend", response_model=GetTrendOutput)
async def http_get_trend(input: GetTrendInput, request: Request) -> GetTrendOutput:
    return await get_trend(input, request.app.state.orchestrator)

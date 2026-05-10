"""MCP server exposing the three Phase 1 tools.

Uses `FastMCP` from the mcp Python SDK. The same tool implementations from
`soundings.tools.*` are used for both transports (HTTP and MCP) — this
module is just the registration boilerplate.

The server is mounted on the FastAPI app at `/mcp` via the SSE sub-app.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

from soundings.tools.find_place import FindPlaceInput, find_place
from soundings.tools.get_indicators import GetIndicatorsInput, get_indicators
from soundings.tools.get_place_profile import GetPlaceProfileInput, get_place_profile

_MCP_SERVER: FastMCP | None = None


def build_mcp_server(state: Any | None = None) -> FastMCP:
    """Build (or return the cached) FastMCP instance.

    `state` is the FastAPI app.state object — passed in by the lifespan so
    tool handlers can reach the orchestrator + geography service. When
    omitted (e.g. in tests), tools are registered against a placeholder
    that raises if invoked.
    """
    global _MCP_SERVER
    if _MCP_SERVER is not None:
        return _MCP_SERVER

    mcp = FastMCP(name="soundings")

    @mcp.tool(name="find_place")
    async def _find_place(query: str, geography_types: list[str] | None = None) -> dict[str, Any]:
        if state is None:
            raise RuntimeError("MCP find_place invoked without app state")
        result = await find_place(
            FindPlaceInput(query=query, geography_types=geography_types),
            state.geography_service,
        )
        return result.model_dump(mode="json")

    @mcp.tool(name="get_indicators")
    async def _get_indicators(
        place_id: str,
        indicators: list[str],
        period: str | None = None,
        format: str = "tall",
    ) -> dict[str, Any]:
        if state is None:
            raise RuntimeError("MCP get_indicators invoked without app state")
        result = await get_indicators(
            GetIndicatorsInput(
                place_id=place_id,
                indicators=indicators,
                period=period,
                format=format,  # type: ignore[arg-type]
            ),
            state.orchestrator,
        )
        return result.model_dump(mode="json")

    @mcp.tool(name="get_place_profile")
    async def _get_place_profile(
        place_id: str, include: list[str] | None = None
    ) -> dict[str, Any]:
        if state is None:
            raise RuntimeError("MCP get_place_profile invoked without app state")
        result = await get_place_profile(
            GetPlaceProfileInput(place_id=place_id, include=include or []),
            state.orchestrator,
            state.engine,
        )
        return result.model_dump(mode="json")

    _MCP_SERVER = mcp
    return mcp

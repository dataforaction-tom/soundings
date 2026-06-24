"""Tool dispatcher mapping Anthropic tool_use blocks to in-process handlers.

The orchestrator inspects the assistant turn for ``tool_use`` blocks, then
delegates each one to this dispatcher. Every non-terminal tool has an async
handler that builds its Pydantic input model, invokes the underlying tool
function against the shared state, and returns ``model_dump(mode="json")``.

``compose_answer`` is the terminal tool: the dispatcher parses it but does
not execute it — the orchestrator owns that step.
"""

from typing import Any

from soundings.ask.blocks import ComposeAnswerArgs
from soundings.tools.compare_places import (
    ComparePlacesInput,
    compare_places,
)
from soundings.tools.compare_places import (
    tool_spec as compare_places_spec,
)
from soundings.tools.find_organisations_in_place import (
    FindOrganisationsInPlaceInput,
    find_organisations_in_place,
)
from soundings.tools.find_organisations_in_place import (
    tool_spec as find_orgs_spec,
)
from soundings.tools.find_place import (
    FindPlaceInput,
    find_place,
)
from soundings.tools.find_place import (
    tool_spec as find_place_spec,
)
from soundings.tools.get_civil_society_profile import (
    GetCivilSocietyProfileInput,
    get_civil_society_profile,
)
from soundings.tools.get_civil_society_profile import (
    tool_spec as get_csp_spec,
)
from soundings.tools.get_indicators import (
    GetIndicatorsInput,
    get_indicators,
)
from soundings.tools.get_indicators import (
    tool_spec as get_indicators_spec,
)
from soundings.tools.get_place_profile import (
    GetPlaceProfileInput,
    get_place_profile,
)
from soundings.tools.get_place_profile import (
    tool_spec as get_place_profile_spec,
)
from soundings.tools.get_trend import (
    GetTrendInput,
    get_trend,
)
from soundings.tools.get_trend import (
    tool_spec as get_trend_spec,
)

TERMINAL_TOOL = "compose_answer"

COMPOSE_ANSWER_DESCRIPTION = (
    "Compose the final answer to the user's question. Each block is rendered "
    "client-side; the orchestrator validates caps (max 20 blocks, max 6 visual)."
)


class ToolDispatcher:
    """Map Anthropic tool_use blocks to in-process Python handlers."""

    def __init__(self, state: Any) -> None:
        self._state = state
        self._fetch_cache: dict[tuple[str, str], Any] = {}
        self._compare_cache: dict[tuple[str, frozenset[str]], Any] = {}
        self._sources: list[Any] = []

    def tool_specs(self) -> list[dict[str, object]]:
        """Return the full tool catalogue including the terminal compose_answer."""
        return [
            find_place_spec(),
            get_indicators_spec(),
            get_place_profile_spec(),
            compare_places_spec(),
            get_trend_spec(),
            find_orgs_spec(),
            get_csp_spec(),
            {
                "name": TERMINAL_TOOL,
                "description": COMPOSE_ANSWER_DESCRIPTION,
                "input_schema": ComposeAnswerArgs.model_json_schema(),
            },
        ]

    def is_terminal_tool(self, tool_name: str) -> bool:
        return tool_name == TERMINAL_TOOL

    def _parse_compose_answer(self, args: dict[str, Any]) -> ComposeAnswerArgs:
        return ComposeAnswerArgs.model_validate(args)

    async def dispatch(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        if tool_name == TERMINAL_TOOL:
            parsed = self._parse_compose_answer(tool_input)
            return parsed.model_dump(mode="json")
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise ValueError(f"Unknown tool: {tool_name}")
        result: dict[str, Any] = await handler(tool_input)
        return result

    @property
    def _handlers(self) -> dict[str, Any]:
        return {
            "find_place": self._handle_find_place,
            "get_indicators": self._handle_get_indicators,
            "get_place_profile": self._handle_get_place_profile,
            "compare_places": self._handle_compare_places,
            "get_trend": self._handle_get_trend,
            "find_organisations_in_place": self._handle_find_organisations,
            "get_civil_society_profile": self._handle_get_csp,
        }

    # --- Non-terminal handlers -------------------------------------------

    async def _handle_find_place(self, args: dict[str, Any]) -> dict[str, Any]:
        model = FindPlaceInput.model_validate(args)
        result = await find_place(model, self._state.geography_service)
        return result.model_dump(mode="json")

    async def _handle_get_indicators(self, args: dict[str, Any]) -> dict[str, Any]:
        model = GetIndicatorsInput.model_validate(args)
        result = await get_indicators(model, self._state.orchestrator)
        return result.model_dump(mode="json")

    async def _handle_get_place_profile(self, args: dict[str, Any]) -> dict[str, Any]:
        model = GetPlaceProfileInput.model_validate(args)
        result = await get_place_profile(model, self._state.orchestrator, self._state.engine)
        return result.model_dump(mode="json")

    async def _handle_compare_places(self, args: dict[str, Any]) -> dict[str, Any]:
        model = ComparePlacesInput.model_validate(args)
        result = await compare_places(model, self._state.orchestrator)
        return result.model_dump(mode="json")

    async def _handle_get_trend(self, args: dict[str, Any]) -> dict[str, Any]:
        model = GetTrendInput.model_validate(args)
        result = await get_trend(model, self._state.orchestrator)
        return result.model_dump(mode="json")

    async def _handle_find_organisations(self, args: dict[str, Any]) -> dict[str, Any]:
        model = FindOrganisationsInPlaceInput.model_validate(args)
        result = await find_organisations_in_place(model, self._state.orchestrator)
        return result.model_dump(mode="json")

    async def _handle_get_csp(self, args: dict[str, Any]) -> dict[str, Any]:
        model = GetCivilSocietyProfileInput.model_validate(args)
        result = await get_civil_society_profile(model, self._state.orchestrator)
        return result.model_dump(mode="json")

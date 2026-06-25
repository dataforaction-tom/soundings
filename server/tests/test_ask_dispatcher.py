"""Unit tests for the ask tool dispatcher."""

from types import SimpleNamespace
from typing import Any

import pytest

from soundings.ask.blocks import ComposeAnswerArgs
from soundings.ask.dispatcher import ToolDispatcher

# --- Fake service objects -------------------------------------------------


class FakeGeographyService:
    async def find_place_by_postcode(self, query: str) -> Any:
        return {}

    async def find_place_by_name(
        self, query: str, geography_types: list[str] | None = None, limit: int = 10
    ) -> Any:
        return []


class FakeOrchestrator:
    async def fetch(self, **kwargs: Any) -> Any:
        return SimpleNamespace(values=[], sources=[], caveats=[], partial=False)

    async def compare_places(self, **kwargs: Any) -> Any:
        return SimpleNamespace(comparisons=[], sources=[], caveats=[], partial=False)

    async def get_trend(self, **kwargs: Any) -> Any:
        return SimpleNamespace(trend=None, sources=[], caveats=[], partial=False)

    async def find_organisations_in_place(self, **kwargs: Any) -> Any:
        return SimpleNamespace(organisations=[], sources=[], caveats=[], partial=False)

    async def compute_civil_society_profile(self, **kwargs: Any) -> Any:
        return SimpleNamespace()


class _FakeConn:
    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, *args: object, **kwargs: object) -> list[tuple[str]]:
        # Stand in for `SELECT key FROM catalogue.indicator`.
        return [("population.total",), ("deprivation.imd.average_score",)]


class FakeEngine:
    def connect(self) -> _FakeConn:
        return _FakeConn()


def _make_dispatcher() -> ToolDispatcher:
    state = SimpleNamespace(
        geography_service=FakeGeographyService(),
        orchestrator=FakeOrchestrator(),
        engine=FakeEngine(),
    )
    return ToolDispatcher(state)


# --- Tests -----------------------------------------------------------------


def test_dispatcher_lists_tool_specs() -> None:
    dispatcher = _make_dispatcher()
    specs = dispatcher.tool_specs()
    names = [s["name"] for s in specs]
    expected = [
        "find_place",
        "get_place_profile",
        "compare_places",
        "get_trend",
        "find_organisations_in_place",
        "get_civil_society_profile",
        "compose_answer",
    ]
    for name in expected:
        assert name in names, f"{name} not in tool specs"
    # Every spec should have the required keys
    for spec in specs:
        assert "name" in spec
        assert "description" in spec
        assert "input_schema" in spec


def test_dispatcher_compose_answer_is_terminal() -> None:
    dispatcher = _make_dispatcher()
    assert dispatcher.is_terminal_tool("compose_answer") is True
    assert dispatcher.is_terminal_tool("find_place") is False


def test_dispatcher_compose_answer_parses_blocks() -> None:
    dispatcher = _make_dispatcher()
    args = {
        "blocks": [
            {"type": "text", "markdown": "Hello **world**"},
            {
                "type": "indicator-card",
                "indicator_key": "population.total",
                "place_id": "ltla24:E06000047",
            },
        ]
    }
    parsed = dispatcher._parse_compose_answer(args)
    assert isinstance(parsed, ComposeAnswerArgs)
    assert len(parsed.blocks) == 2


def test_dispatcher_compose_answer_rejects_invalid() -> None:
    dispatcher = _make_dispatcher()
    args = {"blocks": [{"type": "bogus", "data": "nope"}]}
    with pytest.raises(ValueError):
        dispatcher._parse_compose_answer(args)


@pytest.mark.asyncio
async def test_dispatcher_dispatch_find_place() -> None:
    dispatcher = _make_dispatcher()
    result = await dispatcher.dispatch("find_place", {"query": "Newcastle"})
    assert isinstance(result, dict)
    assert "matches" in result


@pytest.mark.asyncio
async def test_dispatcher_dispatch_compose_answer() -> None:
    dispatcher = _make_dispatcher()
    tool_input = {"blocks": [{"type": "text", "markdown": "hi"}]}
    result = await dispatcher.dispatch("compose_answer", tool_input)
    assert isinstance(result, dict)
    assert "blocks" in result


@pytest.mark.asyncio
async def test_dispatcher_dispatch_unknown_tool_raises() -> None:
    dispatcher = _make_dispatcher()
    with pytest.raises(ValueError, match="Unknown tool"):
        await dispatcher.dispatch("bogus_tool", {})


@pytest.mark.asyncio
async def test_dispatch_drops_blocks_with_unknown_indicator() -> None:
    """Blocks naming a non-catalogue indicator are dropped; a bad-indicator
    map is downgraded to a boundary map rather than dropped."""
    dispatcher = _make_dispatcher()  # FakeEngine knows population.total only-ish
    tool_input = {
        "blocks": [
            {"type": "text", "markdown": "intro"},
            {
                "type": "indicator-card",
                "indicator_key": "population.total",
                "place_id": "ltla24:E06000047",
            },
            {
                "type": "indicator-card",
                "indicator_key": "civil_society.total_organisations",
                "place_id": "ltla24:E06000047",
            },
            {
                "type": "map",
                "place_id": "ltla24:E06000047",
                "indicator_key": "civil_society.total_organisations",
            },
        ]
    }
    result = await dispatcher.dispatch("compose_answer", tool_input)
    blocks = result["blocks"]
    types = [b["type"] for b in blocks]
    # text + valid card + map(boundary) kept; invalid card dropped.
    assert types == ["text", "indicator-card", "map"]
    assert blocks[1]["indicator_key"] == "population.total"
    assert blocks[2]["indicator_key"] is None  # map downgraded to boundary

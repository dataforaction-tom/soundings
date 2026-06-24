"""Unit tests for the AskOrchestrator with mocked Claude responses."""

from typing import Any
from unittest.mock import MagicMock, patch

from soundings.ask.dispatcher import ToolDispatcher
from soundings.ask.orchestrator import AskOrchestrator
from soundings.ask.prompts import SystemPromptBuilder


class _FakeTextBlock:
    """Simulates an Anthropic TextBlock."""

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeToolUseBlock:
    """Simulates an Anthropic ToolUseBlock."""

    def __init__(self, block_id: str, name: str, input_dict: dict[str, Any]) -> None:
        self.type = "tool_use"
        self.id = block_id
        self.name = name
        self.input = input_dict


class _FakeResponse:
    """Simulates an Anthropic Message response."""

    def __init__(self, content: list[Any]) -> None:
        self.content = content
        self.stop_reason = "tool_use"


class _FakeMessages:
    """Simulates client.messages with a queue of responses."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self._call_idx = 0

    def create(self, **kwargs: Any) -> Any:
        if self._call_idx >= len(self._responses):
            raise RuntimeError("No more fake responses")
        resp = self._responses[self._call_idx]
        self._call_idx += 1
        return resp


class _FakeAnthropic:
    """Simulates an Anthropic client."""

    def __init__(self, responses: list[Any]) -> None:
        self.messages = _FakeMessages(responses)


def _make_fake_state() -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        geography_service=MagicMock(),
        orchestrator=MagicMock(),
        engine=MagicMock(),
    )


def _make_dispatcher(state: Any) -> ToolDispatcher:
    return ToolDispatcher(state)


def _collect_events() -> tuple[list[dict[str, Any]], Any]:
    """Returns (events_list, callback) for collecting SSE events."""
    events: list[dict[str, Any]] = []

    def callback(event: dict[str, Any]) -> None:
        events.append(event)

    return events, callback


async def test_orchestrator_streams_status_and_done() -> None:
    """Should emit status events for tool calls and a done event."""
    events, cb = _collect_events()
    state = _make_fake_state()
    dispatcher = _make_dispatcher(state)
    prompt_builder = SystemPromptBuilder(mode="open")

    # Claude first calls find_place, then compose_answer
    responses = [
        _FakeResponse(
            [
                _FakeTextBlock("Looking up Stockton…"),
                _FakeToolUseBlock("tool_1", "find_place", {"query": "Stockton"}),
            ]
        ),
        _FakeResponse(
            [
                _FakeToolUseBlock(
                    "tool_2", "compose_answer", {"blocks": [{"type": "text", "markdown": "Done!"}]}
                ),
            ]
        ),
    ]

    fake_client = _FakeAnthropic(responses)
    with patch("soundings.ask.orchestrator.get_anthropic_client", return_value=fake_client):
        orch = AskOrchestrator(
            dispatcher=dispatcher,
            prompt_builder=prompt_builder,
            api_key="fake-key",
            model="claude-sonnet-4-20250514",
        )
        await orch.run("Tell me about Stockton", cb)

    # Should have status events for tool calls
    status_events = [e for e in events if e["type"] == "status"]
    assert len(status_events) >= 1
    assert "find_place" in status_events[0]["message"]

    # Should have block events from compose_answer
    block_events = [e for e in events if e["type"] == "block"]
    assert len(block_events) == 1
    assert block_events[0]["block"]["type"] == "text"
    assert block_events[0]["block"]["markdown"] == "Done!"

    # Should have a done event
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1


async def test_orchestrator_emits_sources() -> None:
    """Should emit a sources event before done."""
    events, cb = _collect_events()
    state = _make_fake_state()
    dispatcher = _make_dispatcher(state)

    # Manually add a source to the dispatcher
    from datetime import UTC, datetime

    from soundings.contracts.source_ref import SourceRef

    dispatcher._sources.append(
        SourceRef(
            source_id="ons.mid_year_estimates",
            source_label="ONS Mid-Year Estimates",
            publisher="ONS",
            retrieved_at=datetime.now(tz=UTC),
            cache_status="cached",
            licence="OGL",
        )
    )

    prompt_builder = SystemPromptBuilder(mode="open")

    responses = [
        _FakeResponse(
            [
                _FakeToolUseBlock(
                    "tool_1",
                    "compose_answer",
                    {"blocks": [{"type": "text", "markdown": "Answer!"}]},
                ),
            ]
        ),
    ]

    fake_client = _FakeAnthropic(responses)
    with patch("soundings.ask.orchestrator.get_anthropic_client", return_value=fake_client):
        orch = AskOrchestrator(
            dispatcher=dispatcher,
            prompt_builder=prompt_builder,
            api_key="fake-key",
            model="claude-sonnet-4-20250514",
        )
        await orch.run("Stockton", cb)

    sources_events = [e for e in events if e["type"] == "sources"]
    assert len(sources_events) == 1
    assert len(sources_events[0]["sources"]) == 1


async def test_orchestrator_respects_max_iterations() -> None:
    """Should stop and emit error after max iterations."""
    events, cb = _collect_events()
    state = _make_fake_state()
    dispatcher = _make_dispatcher(state)
    prompt_builder = SystemPromptBuilder(mode="open")

    # Claude keeps calling find_place forever
    infinite_responses = [
        _FakeResponse([_FakeToolUseBlock(f"tool_{i}", "find_place", {"query": "x"})])
        for i in range(10)
    ]

    fake_client = _FakeAnthropic(infinite_responses)
    with patch("soundings.ask.orchestrator.get_anthropic_client", return_value=fake_client):
        orch = AskOrchestrator(
            dispatcher=dispatcher,
            prompt_builder=prompt_builder,
            api_key="fake-key",
            model="claude-sonnet-4-20250514",
            max_iterations=3,
        )
        await orch.run("Stockton", cb)

    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1
    assert "iteration" in error_events[0]["message"].lower()


async def test_orchestrator_handles_no_tool_calls() -> None:
    """If Claude responds with text only (no tools), should emit and close."""
    events, cb = _collect_events()
    state = _make_fake_state()
    dispatcher = _make_dispatcher(state)
    prompt_builder = SystemPromptBuilder(mode="open")

    responses = [
        _FakeResponse([_FakeTextBlock("I can't help with that.")]),
    ]

    fake_client = _FakeAnthropic(responses)
    with patch("soundings.ask.orchestrator.get_anthropic_client", return_value=fake_client):
        orch = AskOrchestrator(
            dispatcher=dispatcher,
            prompt_builder=prompt_builder,
            api_key="fake-key",
            model="claude-sonnet-4-20250514",
        )
        await orch.run("What's the weather?", cb)

    # Should emit the text as a block
    block_events = [e for e in events if e["type"] == "block"]
    assert len(block_events) == 1
    assert block_events[0]["block"]["markdown"] == "I can't help with that."

    # Should still emit done
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1


async def test_orchestrator_tool_error_does_not_crash() -> None:
    """If a tool dispatch fails, the error is surfaced as a tool_result."""
    events, cb = _collect_events()
    state = _make_fake_state()
    # Make the dispatcher's find_place handler fail
    state.geography_service = MagicMock()
    state.geography_service.find_place_by_name = MagicMock(
        side_effect=RuntimeError("DB connection failed")
    )
    state.geography_service.find_place_by_postcode = MagicMock(
        side_effect=RuntimeError("DB connection failed")
    )
    dispatcher = _make_dispatcher(state)
    prompt_builder = SystemPromptBuilder(mode="open")

    responses = [
        _FakeResponse(
            [
                _FakeToolUseBlock("tool_1", "find_place", {"query": "Stockton"}),
            ]
        ),
        _FakeResponse(
            [
                _FakeToolUseBlock(
                    "tool_2",
                    "compose_answer",
                    {"blocks": [{"type": "text", "markdown": "Sorry, couldn't find that."}]},
                ),
            ]
        ),
    ]

    fake_client = _FakeAnthropic(responses)
    with patch("soundings.ask.orchestrator.get_anthropic_client", return_value=fake_client):
        orch = AskOrchestrator(
            dispatcher=dispatcher,
            prompt_builder=prompt_builder,
            api_key="fake-key",
            model="claude-sonnet-4-20250514",
        )
        await orch.run("Stockton", cb)

    # Should still get done despite the tool error
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1

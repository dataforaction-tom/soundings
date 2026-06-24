"""AskOrchestrator — runs the Claude tool-use loop and streams SSE events.

The loop:
1. Send the system prompt + user question to Claude with tool definitions.
2. Claude responds with content blocks (text + tool_use).
3. Dispatch each tool_use to the in-process handler via ToolDispatcher.
4. Feed results back to Claude as tool_result messages.
5. Repeat until Claude calls compose_answer (terminal) or max iterations.
6. Stream SSE events: status (per tool call), block (from compose_answer),
   sources (deduped SourceRefs), done.

Uses the non-streaming ``messages.create()`` API — we need full tool_use
blocks before dispatching, so streaming the model response adds complexity
without benefit. The SSE streaming to the UI is handled by the caller,
which receives events via the callback.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from anthropic import Anthropic

from soundings.ask.dispatcher import ToolDispatcher
from soundings.ask.prompts import SystemPromptBuilder

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 12
MAX_TOKENS_OUTPUT = 8192
REQUEST_TIMEOUT_SECONDS = 45

SSECallback = Callable[[dict[str, Any]], Awaitable[None] | None]


def get_anthropic_client(api_key: str) -> Anthropic:
    """Factory so tests can patch the client."""
    return Anthropic(api_key=api_key)


class AskOrchestrator:
    """Runs the Claude tool-use loop, streaming events via callback."""

    def __init__(
        self,
        *,
        dispatcher: ToolDispatcher,
        prompt_builder: SystemPromptBuilder,
        api_key: str,
        model: str,
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        self._dispatcher = dispatcher
        self._prompt_builder = prompt_builder
        self._api_key = api_key
        self._model = model
        self._max_iterations = max_iterations

    async def run(
        self,
        query: str,
        callback: SSECallback,
    ) -> None:
        """Run the tool-use loop, streaming events via callback."""
        client = get_anthropic_client(self._api_key)
        system_prompt = self._prompt_builder.build()
        tool_specs = self._dispatcher.tool_specs()

        messages: list[dict[str, Any]] = [{"role": "user", "content": query}]

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                await self._loop(client, system_prompt, tool_specs, messages, callback)
        except TimeoutError:
            await _emit(callback, {"type": "error", "message": "Request timed out"})
        except Exception as e:
            logger.exception("Ask orchestrator error")
            await _emit(callback, {"type": "error", "message": str(e)})

    async def _loop(
        self,
        client: Anthropic,
        system_prompt: str,
        tool_specs: list[dict[str, object]],
        messages: list[dict[str, Any]],
        callback: SSECallback,
    ) -> None:
        for _iteration in range(self._max_iterations):
            response = client.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS_OUTPUT,
                system=system_prompt,
                tools=tool_specs,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
            )

            # Collect content blocks from the response
            assistant_content: list[dict[str, Any]] = []
            tool_use_blocks: list[dict[str, Any]] = []

            for content_block in response.content:
                if content_block.type == "text":
                    assistant_content.append(
                        {
                            "type": "text",
                            "text": content_block.text,
                        }
                    )
                elif content_block.type == "tool_use":
                    tool_use_blocks.append(
                        {
                            "type": "tool_use",
                            "id": content_block.id,
                            "name": content_block.name,
                            "input": content_block.input,
                        }
                    )
                    assistant_content.append(
                        {
                            "type": "tool_use",
                            "id": content_block.id,
                            "name": content_block.name,
                            "input": content_block.input,
                        }
                    )

            messages.append({"role": "assistant", "content": assistant_content})

            if not tool_use_blocks:
                # No tool calls — Claude is done talking without compose_answer.
                # Emit any text as a block, then close.
                for content_block in response.content:
                    if content_block.type == "text" and content_block.text.strip():
                        await _emit(
                            callback,
                            {
                                "type": "block",
                                "block": {"type": "text", "markdown": content_block.text},
                            },
                        )
                await _emit(
                    callback,
                    {
                        "type": "sources",
                        "sources": [s.model_dump(mode="json") for s in self._dispatcher.sources],
                    },
                )
                await _emit(callback, {"type": "done"})
                return

            # Dispatch each tool call
            tool_results: list[dict[str, Any]] = []
            for tb in tool_use_blocks:
                name = tb["name"]
                tool_input = tb["input"]

                if self._dispatcher.is_terminal_tool(name):
                    # compose_answer — parse blocks and emit
                    parsed = self._dispatcher._parse_compose_answer(tool_input)
                    for block in parsed.blocks:
                        await _emit(
                            callback,
                            {
                                "type": "block",
                                "block": block.model_dump(mode="json"),
                            },
                        )

                    sources = [s.model_dump(mode="json") for s in self._dispatcher.sources]
                    await _emit(callback, {"type": "sources", "sources": sources})
                    await _emit(callback, {"type": "done"})
                    return

                # Non-terminal tool — dispatch and emit status
                await _emit(callback, {"type": "status", "message": f"Calling {name}…"})
                try:
                    result = await self._dispatcher.dispatch(name, tool_input)
                except Exception as e:
                    logger.warning("Tool %s failed: %s", name, e)
                    result = {"error": str(e)}

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tb["id"],
                        "content": str(result),
                    }
                )

            messages.append({"role": "user", "content": tool_results})
            continue

        # Max iterations exceeded
        await _emit(
            callback,
            {
                "type": "error",
                "message": f"Exceeded max iterations ({self._max_iterations})",
            },
        )


async def _emit(callback: SSECallback, event: dict[str, Any]) -> None:
    """Call the callback, awaiting if it returns a coroutine."""
    result = callback(event)
    if asyncio.iscoroutine(result):
        await result

"""HTTP route for /v1/ask — the natural-language ask interface.

POST /v1/ask with {query, place_id?, mode?} → SSE stream of events.
"""

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from soundings.ask.dispatcher import ToolDispatcher
from soundings.ask.orchestrator import AskOrchestrator
from soundings.ask.prompts import AskMode, SystemPromptBuilder
from soundings.core.config import get_settings

router = APIRouter(prefix="/v1")


class AskInput(BaseModel):
    query: str
    place_id: str | None = None
    mode: AskMode = "open"


@router.post("/ask")
async def ask(input: AskInput, request: Request) -> StreamingResponse:
    if not input.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")

    # Build place context if a place_id is provided
    place_name: str | None = None
    if input.place_id:
        from sqlalchemy import text

        async with request.app.state.engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT name FROM geography.place WHERE id = :id"),
                    {"id": input.place_id},
                )
            ).first()
        if row:
            place_name = row.name

    prompt_builder = SystemPromptBuilder(
        mode=input.mode,
        place_name=place_name,
        place_id=input.place_id,
    )

    dispatcher = ToolDispatcher(request.app.state)

    orchestrator = AskOrchestrator(
        dispatcher=dispatcher,
        prompt_builder=prompt_builder,
        api_key=settings.anthropic_api_key,
        model=settings.ask_model,
    )

    async def event_stream() -> Any:
        queue: asyncio.Queue[str] = asyncio.Queue()

        async def callback(event: dict[str, Any]) -> None:
            await queue.put(json.dumps(event))

        # Run the orchestrator in the background
        task = asyncio.create_task(orchestrator.run(input.query, callback))

        # Stream events as SSE
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=45.0)
                yield f"data: {data}\n\n"
                event_obj = json.loads(data)
                if event_obj.get("type") in ("done", "error"):
                    break
            except TimeoutError:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Stream timeout'})}\n\n"
                break

        # Ensure the task completes
        await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

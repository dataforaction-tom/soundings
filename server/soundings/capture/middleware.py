"""CaptureMiddleware — wraps every `/v1/tools/*` POST.

Pre-call work:
    1. Reads the SessionState attached by SessionMiddleware (Task 3).
    2. Reads the request JSON body, pops `nl_question` (kept only under
       `consent_level == "full"`; otherwise discarded immediately).
    3. Re-emits the body to the downstream handler.

Post-call work:
    4. Reads the response JSON, extracts capture-relevant fields
       (`indicators_returned`, `sources_used`, `geography_referenced`,
       `result_status`, `error_class`).
    5. Builds a CaptureContext and hands it to `app.state.raw_writer`
       (a duck-typed object with an async `write(ctx)` method). The
       real writer arrives in Task 6; tests inject a fake.

Implemented as a raw ASGI middleware rather than Starlette's
`BaseHTTPMiddleware` because we need to mutate the request body before
it reaches the downstream handler — `BaseHTTPMiddleware` doesn't let
the inner app see a modified body even if you reassign
`request._receive`.

If `app.state.raw_writer` is not set, the middleware is a no-op
pass-through — this keeps the existing test suite from breaking before
Task 6 wires the real writer into app startup.
"""

import asyncio
import json
from typing import Any, Protocol
from uuid import UUID

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from soundings.capture.context import CaptureContext
from soundings.http.session import (
    cookies_from_asgi_scope,
    session_state_from_cookies,
)

TOOLS_PATH_PREFIX = "/v1/tools/"
ASK_PATH = "/v1/ask"


class RawWriter(Protocol):
    async def write(self, ctx: CaptureContext) -> UUID | None: ...


class SanitiserScheduler(Protocol):
    """Anything with an async `sanitise(record_id)` — SanitiserWorker fits."""

    async def sanitise(self, record_id: UUID) -> None: ...


class _RateLimiter(Protocol):
    async def should_downgrade(self, session_id: UUID) -> bool: ...


def _extract_tool_name(path: str) -> str:
    if path == ASK_PATH:
        return "ask"
    return path[len(TOOLS_PATH_PREFIX) :].split("/", 1)[0]


def _safe_json_loads(blob: bytes) -> Any:
    try:
        return json.loads(blob) if blob else None
    except json.JSONDecodeError:
        return None


def _schedule_sanitiser(app_obj: Any, record_id: UUID) -> None:
    """Fire-and-forget the sanitiser via `asyncio.create_task`.

    Holds a strong reference in `app.state.background_tasks` so the event
    loop can't GC the task before it completes — a known FastAPI/asyncio
    footgun under memory pressure. The task removes itself from the set
    on completion via add_done_callback.
    """
    if app_obj is None:
        return
    sanitiser: SanitiserScheduler | None = getattr(app_obj.state, "sanitiser_worker", None)
    if sanitiser is None:
        return
    background_tasks: set[asyncio.Task[None]] | None = getattr(
        app_obj.state, "background_tasks", None
    )
    if background_tasks is None:
        # Lifespan didn't initialise the set — be defensive rather than crash
        # (some tests construct an app without it).
        background_tasks = set()
        app_obj.state.background_tasks = background_tasks

    task = asyncio.create_task(sanitiser.sanitise(record_id))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


def _extract_capture_fields(
    response_payload: Any,
    *,
    is_sse: bool = False,
    response_bytes: bytes = b"",
) -> dict[str, Any]:
    """Best-effort pull of tool-response fields into the capture record.

    For SSE streams (/v1/ask), parse each ``data:`` frame as JSON and
    merge indicators / sources / geography across all frames. The final
    ``done`` or ``error`` event determines ``result_status``.
    """
    if is_sse:
        return _extract_sse_capture_fields(response_bytes)
    if not isinstance(response_payload, dict):
        return {
            "indicators_returned": [],
            "sources_used": [],
            "geography_referenced": [],
            "result_status": "error",
            "error_class": None,
        }

    indicators: list[str] = []
    sources: list[str] = []
    geography: list[dict[str, str]] = []

    for row in response_payload.get("results", []) or []:
        if isinstance(row, dict):
            if (key := row.get("indicator")) is not None:
                indicators.append(str(key))
            src = row.get("source")
            if isinstance(src, dict) and (sid := src.get("source_id")) is not None:
                sources.append(str(sid))
    for match in response_payload.get("matches", []) or []:
        if isinstance(match, dict):
            gid = match.get("id")
            gtype = match.get("type")
            if gid and gtype:
                geography.append({"id": str(gid), "type": str(gtype)})

    place = response_payload.get("place")
    if isinstance(place, dict) and place.get("id") and place.get("type"):
        geography.append({"id": str(place["id"]), "type": str(place["type"])})

    err = response_payload.get("error")
    result_status = "error" if isinstance(err, dict) else "ok"
    error_class = err.get("code") if isinstance(err, dict) else None

    return {
        "indicators_returned": indicators,
        "sources_used": list(dict.fromkeys(sources)),
        "geography_referenced": geography,
        "result_status": result_status,
        "error_class": error_class,
    }


def _extract_sse_capture_fields(response_bytes: bytes) -> dict[str, Any]:
    """Parse SSE stream bytes and extract capture fields.

    Each frame is ``data: {json}\\n\\n``. We look for ``done`` / ``error``
    events to determine status, and collect indicators / sources / geography
    from ``block`` events that carry tool results.
    """
    text = response_bytes.decode("utf-8", errors="replace")
    indicators: list[str] = []
    sources: list[str] = []
    geography: list[dict[str, str]] = []
    result_status = "ok"
    error_class: str | None = None

    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(evt, dict):
            continue
        evt_type = evt.get("type", "")
        if evt_type == "error":
            result_status = "error"
            error_class = "ask_error"
        elif evt_type == "done":
            result_status = "ok"
        elif evt_type == "sources":
            for src in evt.get("sources", []) or []:
                if isinstance(src, dict) and src.get("source_id"):
                    sources.append(str(src["source_id"]))
        elif evt_type == "block":
            block = evt.get("block", {})
            if isinstance(block, dict):
                for row in block.get("results", []) or []:
                    if isinstance(row, dict):
                        if (key := row.get("indicator")) is not None:
                            indicators.append(str(key))
                        src = row.get("source")
                        if isinstance(src, dict) and (sid := src.get("source_id")) is not None:
                            sources.append(str(sid))
                place = block.get("place")
                if isinstance(place, dict) and place.get("id") and place.get("type"):
                    geography.append({"id": str(place["id"]), "type": str(place["type"])})

    return {
        "indicators_returned": indicators,
        "sources_used": list(dict.fromkeys(sources)),
        "geography_referenced": geography,
        "result_status": result_status,
        "error_class": error_class,
    }


class CaptureMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not (
            scope["path"].startswith(TOOLS_PATH_PREFIX) or scope["path"] == ASK_PATH
        ):
            await self.app(scope, receive, send)
            return

        # Parse the session directly from the raw ASGI scope so we don't
        # depend on whether SessionMiddleware has run upstream (it has, but
        # the dependency would be implicit and fragile across Starlette
        # versions). Short-circuit before touching the request body if
        # there's no capture work to do.
        session = session_state_from_cookies(cookies_from_asgi_scope(scope))
        app_obj = scope.get("app")
        writer: RawWriter | None = (
            getattr(app_obj.state, "raw_writer", None) if app_obj is not None else None
        )
        if writer is None or session.consent_level == "none":
            await self.app(scope, receive, send)
            return

        # Rate-limit silent downgrade: if this session has exceeded the
        # full-consent per-hour cap (spec §8.3), demote this record to
        # `minimal` before anything else runs. The asker sees no error.
        effective_consent = session.consent_level
        if effective_consent == "full" and session.session_id is not None:
            limiter: _RateLimiter | None = (
                getattr(app_obj.state, "rate_limiter", None) if app_obj is not None else None
            )
            if limiter is not None and await limiter.should_downgrade(session.session_id):
                effective_consent = "minimal"

        # Drain the request body so we can inspect and possibly rewrite it.
        body_chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            body_chunks.append(message.get("body", b""))
            more_body = message.get("more_body", False)
        body_bytes = b"".join(body_chunks)

        body_json = _safe_json_loads(body_bytes)
        tool_inputs: dict[str, Any] = body_json if isinstance(body_json, dict) else {}

        nl_question: str | None = None
        if effective_consent == "full":
            # /v1/ask sends the question as "query"; /v1/tools/* may carry
            # it as "nl_question" (the find_place tool accepts it).
            raw_q = tool_inputs.get("nl_question")
            if isinstance(raw_q, str):
                nl_question = raw_q
            elif scope["path"] == ASK_PATH and isinstance(tool_inputs.get("query"), str):
                nl_question = tool_inputs["query"]
        tool_inputs.pop("nl_question", None)

        replay_body = (
            json.dumps(tool_inputs).encode("utf-8") if isinstance(body_json, dict) else body_bytes
        )

        replay_sent = False

        async def replay_receive() -> Message:
            nonlocal replay_sent
            if replay_sent:
                # The downstream handler has already consumed the body. Delegate
                # to the real receive() so any further reads block on the actual
                # client connection. Returning a synthetic `http.disconnect` here
                # tells a StreamingResponse's disconnect-watcher that the client
                # vanished, which cancels the stream mid-flight — fatal for the
                # SSE `/v1/ask` endpoint.
                return await receive()
            replay_sent = True
            return {"type": "http.request", "body": replay_body, "more_body": False}

        # Stream the response straight through to the client while teeing a copy
        # of the body for capture. The middleware never rewrites the response —
        # it only inspects it — so there's no need to buffer the whole thing
        # first. Buffering would defeat streaming endpoints like `/v1/ask`, which
        # emit Server-Sent Events incrementally.
        response_body_chunks: list[bytes] = []

        async def teeing_send(message: Message) -> None:
            if message["type"] == "http.response.body":
                response_body_chunks.append(message.get("body", b""))
            await send(message)

        await self.app(scope, replay_receive, teeing_send)

        response_bytes = b"".join(response_body_chunks)

        is_sse = scope["path"] == ASK_PATH
        response_payload = _safe_json_loads(response_bytes)
        extras = _extract_capture_fields(
            response_payload,
            is_sse=is_sse,
            response_bytes=response_bytes,
        )
        ctx = CaptureContext(
            session_id=session.session_id,
            consent_level=effective_consent,
            consent_version=session.consent_version,
            tool_called=_extract_tool_name(scope["path"]),
            tool_inputs=tool_inputs,
            natural_language_question=nl_question,
            asker_sector=session.asker_sector,
            asker_purpose=None,
            result_status=extras["result_status"],
            error_class=extras["error_class"],
            indicators_returned=extras["indicators_returned"],
            sources_used=extras["sources_used"],
            geography_referenced=extras["geography_referenced"],
        )
        record_id = await writer.write(ctx)
        if record_id is not None:
            _schedule_sanitiser(app_obj, record_id)

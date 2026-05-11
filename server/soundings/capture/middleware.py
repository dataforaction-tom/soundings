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

import json
from typing import Any, Protocol

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from soundings.capture.context import CaptureContext
from soundings.http.session import SessionState

TOOLS_PATH_PREFIX = "/v1/tools/"


class RawWriter(Protocol):
    async def write(self, ctx: CaptureContext) -> None: ...


def _extract_tool_name(path: str) -> str:
    # /v1/tools/find_place → "find_place"
    return path[len(TOOLS_PATH_PREFIX) :].split("/", 1)[0]


def _safe_json_loads(blob: bytes) -> Any:
    try:
        return json.loads(blob) if blob else None
    except json.JSONDecodeError:
        return None


def _extract_capture_fields(response_payload: Any) -> dict[str, Any]:
    """Best-effort pull of tool-response fields into the capture record."""
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


class CaptureMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(TOOLS_PATH_PREFIX):
            await self.app(scope, receive, send)
            return

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

        # SessionMiddleware (Task 3) puts a SessionState on `scope["state"]`
        # via `request.state.session = ...`. If it didn't run upstream, we
        # treat the caller as anonymous (consent="none", no capture).
        state = scope.get("state") or {}
        session: SessionState | None = state.get("session") if isinstance(state, dict) else None
        session_consent = session.consent_level if session is not None else "none"

        nl_question: str | None = None
        if session_consent == "full" and isinstance(tool_inputs.get("nl_question"), str):
            nl_question = tool_inputs["nl_question"]
        tool_inputs.pop("nl_question", None)

        replay_body = (
            json.dumps(tool_inputs).encode("utf-8") if isinstance(body_json, dict) else body_bytes
        )

        replay_sent = False

        async def replay_receive() -> Message:
            nonlocal replay_sent
            if replay_sent:
                # Once the downstream handler has consumed the body, any
                # subsequent receive() should not deliver another body —
                # block waiting for a disconnect message.
                return {"type": "http.disconnect"}
            replay_sent = True
            return {"type": "http.request", "body": replay_body, "more_body": False}

        # Buffer the response so we can inspect + rebuild it.
        response_status = 500
        response_headers: list[tuple[bytes, bytes]] = []
        response_body_chunks: list[bytes] = []

        async def buffered_send(message: Message) -> None:
            nonlocal response_status, response_headers
            if message["type"] == "http.response.start":
                response_status = message["status"]
                response_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                response_body_chunks.append(message.get("body", b""))

        await self.app(scope, replay_receive, buffered_send)

        response_bytes = b"".join(response_body_chunks)

        # Capture path: only when we have a writer, a session, and consent
        # above 'none'. Otherwise just forward the response unchanged.
        app_obj = scope.get("app")
        writer: RawWriter | None = (
            getattr(app_obj.state, "raw_writer", None) if app_obj is not None else None
        )

        if writer is not None and session is not None and session.consent_level != "none":
            response_payload = _safe_json_loads(response_bytes)
            extras = _extract_capture_fields(response_payload)
            ctx = CaptureContext(
                session_id=session.session_id,
                consent_level=session.consent_level,
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
            await writer.write(ctx)

        # Forward buffered response to the real downstream send.
        await send(
            {
                "type": "http.response.start",
                "status": response_status,
                "headers": response_headers,
            }
        )
        await send({"type": "http.response.body", "body": response_bytes, "more_body": False})

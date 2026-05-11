"""Session/consent cookie middleware.

Reads three cookies on every request:
    soundings_session  → UUID identifying the per-session corpus rows
    soundings_consent  → "full" | "minimal" | "none"
    soundings_sector   → one of capture.consent.ASKER_SECTORS

Attaches a SessionState to `request.state.session`. Does NOT emit
Set-Cookie headers — that's the job of `POST /v1/capture/consent`
(Task 4). Malformed cookie values are silently dropped (the caller
remains anonymous) rather than failing the request.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from soundings.capture.consent import (
    ASKER_SECTORS,
    CONSENT_LEVELS,
    CONSENT_VERSION,
)
from soundings.capture.context import AskerSector, ConsentLevel


@dataclass
class SessionState:
    session_id: UUID | None
    consent_level: ConsentLevel
    consent_version: str
    asker_sector: AskerSector | None


def _parse_session_id(raw: str | None) -> UUID | None:
    if not raw:
        return None
    try:
        return UUID(raw)
    except (ValueError, AttributeError):
        return None


def _parse_consent_level(raw: str | None) -> ConsentLevel:
    if raw in CONSENT_LEVELS:
        return raw
    # Absent or malformed cookie ⇒ no capture by default. The UI walks the
    # user through `POST /v1/capture/consent` on first visit to pick one.
    return "none"


def _parse_sector(raw: str | None) -> AskerSector | None:
    if raw in ASKER_SECTORS:
        return raw
    return None


def session_state_from_cookies(cookies: Mapping[str, str]) -> SessionState:
    """Build a SessionState from parsed cookies.

    Shared by SessionMiddleware (which gets cookies via Starlette's Request)
    and CaptureMiddleware (which parses ASGI scope headers directly so it
    doesn't depend on SessionMiddleware's `request.state` output).
    """
    return SessionState(
        session_id=_parse_session_id(cookies.get("soundings_session")),
        consent_level=_parse_consent_level(cookies.get("soundings_consent")),
        consent_version=CONSENT_VERSION,
        asker_sector=_parse_sector(cookies.get("soundings_sector")),
    )


def cookies_from_asgi_scope(scope: Mapping[str, object]) -> dict[str, str]:
    """Extract `Cookie:` header value(s) from a raw ASGI scope into a dict."""
    headers = scope.get("headers") or []
    if not isinstance(headers, list):
        return {}
    cookies: dict[str, str] = {}
    for raw_name, raw_value in headers:
        if raw_name == b"cookie":
            for pair in raw_value.decode("latin-1").split(";"):
                pair = pair.strip()
                if "=" in pair:
                    name, value = pair.split("=", 1)
                    cookies[name] = value
    return cookies


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.session = session_state_from_cookies(request.cookies)
        return await call_next(request)

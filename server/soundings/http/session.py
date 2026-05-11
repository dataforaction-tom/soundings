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


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.session = SessionState(
            session_id=_parse_session_id(request.cookies.get("soundings_session")),
            consent_level=_parse_consent_level(request.cookies.get("soundings_consent")),
            consent_version=CONSENT_VERSION,
            asker_sector=_parse_sector(request.cookies.get("soundings_sector")),
        )
        return await call_next(request)

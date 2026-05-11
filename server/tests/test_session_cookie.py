from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from soundings.capture.consent import CONSENT_VERSION
from soundings.http.session import SessionMiddleware, SessionState


@pytest.fixture
def app_with_session_echo() -> FastAPI:
    """Tiny FastAPI app that returns its request.state.session as JSON."""
    app = FastAPI()
    app.add_middleware(SessionMiddleware)

    @app.get("/echo")
    async def echo(request: Request) -> dict[str, str | None]:
        session: SessionState = request.state.session
        return {
            "session_id": str(session.session_id) if session.session_id else None,
            "consent_level": session.consent_level,
            "consent_version": session.consent_version,
            "asker_sector": session.asker_sector,
        }

    return app


async def test_request_with_no_cookies_yields_anonymous_session(
    app_with_session_echo: FastAPI,
) -> None:
    transport = httpx.ASGITransport(app=app_with_session_echo)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/echo")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] is None
    assert body["consent_level"] == "none"
    assert body["consent_version"] == CONSENT_VERSION
    assert body["asker_sector"] is None
    # No Set-Cookie should be emitted by the middleware — only the consent
    # endpoint (Task 4) issues cookies.
    assert "set-cookie" not in response.headers


async def test_valid_cookies_populate_session_state(
    app_with_session_echo: FastAPI,
) -> None:
    session_id = uuid4()
    cookies = {
        "soundings_session": str(session_id),
        "soundings_consent": "full",
        "soundings_sector": "charity",
    }
    transport = httpx.ASGITransport(app=app_with_session_echo)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        response = await client.get("/echo")

    body = response.json()
    assert UUID(body["session_id"]) == session_id
    assert body["consent_level"] == "full"
    assert body["asker_sector"] == "charity"


async def test_malformed_session_uuid_is_silently_dropped(
    app_with_session_echo: FastAPI,
) -> None:
    cookies = {
        "soundings_session": "not-a-uuid",
        "soundings_consent": "minimal",
    }
    transport = httpx.ASGITransport(app=app_with_session_echo)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        response = await client.get("/echo")

    body = response.json()
    assert body["session_id"] is None
    # Consent level still honoured even without a valid session_id — the
    # caller can pick none/minimal/full anonymously.
    assert body["consent_level"] == "minimal"


async def test_invalid_sector_is_cleared_to_none(
    app_with_session_echo: FastAPI,
) -> None:
    cookies = {
        "soundings_session": str(uuid4()),
        "soundings_consent": "full",
        "soundings_sector": "philanthropist",  # not in vocabulary
    }
    transport = httpx.ASGITransport(app=app_with_session_echo)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as client:
        response = await client.get("/echo")

    body = response.json()
    assert body["asker_sector"] is None
    assert body["consent_level"] == "full"

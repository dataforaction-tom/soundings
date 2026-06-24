"""Integration tests for the /v1/ask endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


async def test_ask_returns_400_on_empty_query() -> None:
    from soundings.app import app

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/v1/ask", json={"query": ""})
    assert response.status_code == 400


async def test_ask_returns_422_on_bad_mode() -> None:
    from soundings.app import app

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/v1/ask", json={"query": "Stockton", "mode": "bad"})
    assert response.status_code == 422


async def test_ask_returns_503_without_api_key() -> None:
    from soundings.app import app
    from soundings.core.config import get_settings

    # Temporarily remove the API key
    settings = get_settings()
    original_key = settings.anthropic_api_key
    settings.anthropic_api_key = ""

    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                response = await ac.post("/v1/ask", json={"query": "Stockton"})
        assert response.status_code == 503
    finally:
        settings.anthropic_api_key = original_key

import pytest
from httpx import ASGITransport, AsyncClient

from soundings.app import app

pytestmark = pytest.mark.integration


async def test_healthz_returns_ok_when_db_reachable_and_catalogue_loaded() -> None:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["postgres"] == "ok"
    assert body["checks"]["catalogue"] == "ok"

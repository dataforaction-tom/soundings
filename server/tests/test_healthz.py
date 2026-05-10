import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from soundings.app import app
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_recent_loader_runs() -> None:
    """Stamp a recent successful run for every loader-mode source so the
    healthz loader_runs check doesn't drag the overall status to degraded
    on a fresh DB."""
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        sources = (
            await conn.execute(
                text("SELECT id FROM catalogue.source WHERE mode = 'loader'")
            )
        ).all()
        for row in sources:
            await conn.execute(
                text(
                    "INSERT INTO data.loader_run "
                    "(id, source_id, started_at, finished_at, status, rows_written) "
                    "VALUES (:id, :sid, :s, :f, 'ok', 1)"
                ),
                {
                    "id": uuid.uuid4(),
                    "sid": row.id,
                    "s": now - timedelta(minutes=5),
                    "f": now,
                },
            )


async def test_healthz_returns_ok_when_db_catalogue_and_loaders_fresh() -> None:
    async with app.router.lifespan_context(app):
        await _seed_recent_loader_runs()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["postgres"] == "ok"
    assert body["checks"]["catalogue"] == "ok"
    assert body["checks"]["loader_runs"] == "ok"
    assert body["status"] == "ok"


async def test_healthz_degrades_when_loader_runs_are_stale() -> None:
    # No loader_runs seeded → every loader source is stale.
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.loader_run"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/healthz")
    body = response.json()
    assert body["status"] == "degraded"
    assert "stale" in body["checks"]["loader_runs"]

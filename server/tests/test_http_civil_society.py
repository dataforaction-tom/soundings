"""HTTP end-to-end for /v1/tools/get_civil_society_profile.

Uses ASGITransport + the FastAPI lifespan to spin the app up against a
seeded test DB."""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text

from soundings.app import app
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_minimum() -> None:
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        # Scope cleanup to the test-owned place only, avoiding FK violations
        # on indicator_value rows left by other tests / seed runs.
        await conn.execute(
            text("DELETE FROM data.organisation_operates_in WHERE place_id = 'ltla24:H01'")
        )
        await conn.execute(text("DELETE FROM data.organisation WHERE id = 'h1'"))
        await conn.execute(text("DELETE FROM geography.place WHERE id = 'ltla24:H01'"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:H01', 'ltla24', 'H01', 'HTTP test place')"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO data.organisation "
                "(id, name, classification, source_id, retrieved_at, raw) "
                "VALUES ('h1', 'HTTP Trust', ARRAY[]::varchar[], 'charity_commission', :r, "
                " CAST(:raw AS jsonb))"
            ),
            {
                "r": now,
                "raw": '{"latest_income": 50000, "date_of_registration": "2019-05-01"}',
            },
        )
        await conn.execute(
            text(
                "INSERT INTO data.organisation_operates_in "
                "(organisation_id, place_id) VALUES ('h1', 'ltla24:H01')"
            )
        )


async def test_http_get_civil_society_profile_returns_aggregates() -> None:
    await _seed_minimum()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/tools/get_civil_society_profile",
                json={"place_id": "ltla24:H01"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["place_id"] == "ltla24:H01"
    assert body["total_organisations"] == 1
    assert body["with_reported_income"] == 1
    assert body["median_income"] == 50000.0
    assert body["income_buckets"][1]["label"] == "10k-100k"
    assert body["income_buckets"][1]["count"] == 1
    assert body["registration_cohort"][0]["year"] == 2019

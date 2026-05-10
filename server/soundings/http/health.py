from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select, text

from soundings.adapters.base import _cron_to_window_days
from soundings.db.engine import get_engine
from soundings.db.models.catalogue import Source

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    checks: dict[str, str] = {}

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"fail: {exc.__class__.__name__}"

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            n_sources = (await conn.execute(select(func.count(Source.id)))).scalar_one()
        checks["catalogue"] = "ok" if n_sources > 0 else "empty"
    except Exception as exc:
        checks["catalogue"] = f"fail: {exc.__class__.__name__}"

    try:
        engine = get_engine()
        stale = await _stale_loader_sources(engine)
        checks["loader_runs"] = "ok" if not stale else f"stale: {','.join(stale)}"
    except Exception as exc:
        checks["loader_runs"] = f"fail: {exc.__class__.__name__}"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}


async def _stale_loader_sources(engine: object) -> list[str]:
    """Return source_ids whose last successful loader_run is older than
    1.5× refresh_cadence. Sources that have never run successfully are
    listed too.
    """
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT s.id, s.refresh_cadence,
                           (
                               SELECT MAX(finished_at) FROM data.loader_run
                               WHERE source_id = s.id AND status = 'ok'
                           ) AS last_ok
                    FROM catalogue.source s
                    WHERE s.mode = 'loader'
                    """
                )
            )
        ).all()

    now = datetime.now(tz=UTC)
    stale: list[str] = []
    for row in rows:
        window_days = _cron_to_window_days(row.refresh_cadence)
        threshold = timedelta(days=int(window_days * 1.5))
        if row.last_ok is None:
            stale.append(row.id)
            continue
        if now - row.last_ok > threshold:
            stale.append(row.id)
    return stale

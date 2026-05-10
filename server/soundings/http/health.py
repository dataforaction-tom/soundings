from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select, text

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

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}

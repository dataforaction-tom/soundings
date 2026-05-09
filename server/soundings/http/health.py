from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from soundings.db.engine import get_engine

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    checks: dict[str, str] = {}
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = f"fail: {exc.__class__.__name__}"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}

"""GET /v1/catalogue/indicators — full indicator catalogue from Postgres."""

from fastapi import APIRouter, Request
from sqlalchemy import text

router = APIRouter(prefix="/v1/catalogue")


@router.get("/indicators")
async def list_indicators(request: Request) -> dict[str, object]:
    engine = request.app.state.engine
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT key, label, description, unit, higher_is, source_id,
                           available_at, refresh_cadence, caveats, related_keys,
                           catalogue_version
                    FROM catalogue.indicator
                    ORDER BY key
                    """
                )
            )
        ).all()
        version = (
            await conn.execute(
                text(
                    "SELECT catalogue_version FROM catalogue.indicator "
                    "WHERE catalogue_version IS NOT NULL LIMIT 1"
                )
            )
        ).first()
    return {
        "catalogue_version": version.catalogue_version if version else None,
        "indicators": [
            {
                "key": r.key,
                "label": r.label,
                "description": r.description,
                "unit": r.unit,
                "higher_is": r.higher_is,
                "source_id": r.source_id,
                "available_at": list(r.available_at or []),
                "refresh_cadence": r.refresh_cadence,
                "caveats": list(r.caveats or []),
                "related_keys": list(r.related_keys or []),
            }
            for r in rows
        ],
    }

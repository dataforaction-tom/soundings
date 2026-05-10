"""GET /v1/sources — list catalogue sources with last loader_run metadata."""

from fastapi import APIRouter, Request
from sqlalchemy import text

router = APIRouter(prefix="/v1")


@router.get("/sources")
async def list_sources(request: Request) -> dict[str, list[dict[str, object]]]:
    engine = request.app.state.engine
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT
                        s.id,
                        s.label,
                        s.publisher,
                        s.publisher_url,
                        s.dataset_url,
                        s.licence,
                        s.mode,
                        s.refresh_cadence,
                        (
                            SELECT finished_at FROM data.loader_run
                            WHERE source_id = s.id AND status = 'ok'
                            ORDER BY finished_at DESC LIMIT 1
                        ) AS last_finished_at,
                        (
                            SELECT status FROM data.loader_run
                            WHERE source_id = s.id
                            ORDER BY COALESCE(finished_at, started_at) DESC LIMIT 1
                        ) AS last_status
                    FROM catalogue.source s
                    ORDER BY s.id
                    """
                )
            )
        ).all()
    return {
        "sources": [
            {
                "id": r.id,
                "label": r.label,
                "publisher": r.publisher,
                "publisher_url": r.publisher_url,
                "dataset_url": r.dataset_url,
                "licence": r.licence,
                "mode": r.mode,
                "refresh_cadence": r.refresh_cadence,
                "last_finished_at": (
                    r.last_finished_at.isoformat() if r.last_finished_at else None
                ),
                "last_status": r.last_status,
            }
            for r in rows
        ]
    }

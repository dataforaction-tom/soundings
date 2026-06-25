"""GET /v1/place/{place_id}/geometry and GET /v1/place/{place_id}/peers/geometry.

Returns simplified GeoJSON for a single place or its peers (same `type`,
excluding the place itself). Geometries are simplified with
ST_Simplify(geom, 0.005) and serialised via ST_AsGeoJSON.

Peer geometries optionally join `data.indicator_value` to attach the
indicator value and percentile for a given indicator/period.
"""

import json

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text

router = APIRouter(prefix="/v1")


@router.get("/place/{place_id}/geometry")
async def get_place_geometry(request: Request, place_id: str) -> dict[str, object]:
    engine = request.app.state.engine
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT
                        p.id,
                        p.name,
                        p.type,
                        ST_AsGeoJSON(ST_Simplify(p.geom, 0.005)) AS geojson
                    FROM geography.place p
                    WHERE p.id = :place_id
                    """
                ),
                {"place_id": place_id},
            )
        ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="place not found")
    geometry = _parse_geojson(row.geojson)
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "id": row.id,
            "name": row.name,
            "type": row.type,
        },
    }


def _parse_geojson(geojson_str: str | None) -> dict[str, object] | None:
    """ST_AsGeoJSON returns a text JSON string; parse it, or None if NULL."""
    if geojson_str is None:
        return None
    return json.loads(geojson_str)

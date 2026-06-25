"""GET /v1/place/{place_id}/geometry and GET /v1/place/{place_id}/peers/geometry.

Returns simplified GeoJSON for a single place or its peers (same `type`,
excluding the place itself). Geometries are simplified with
ST_Simplify(geom, 0.005) and serialised via ST_AsGeoJSON.

Peer geometries optionally join `data.indicator_value` to attach the
indicator value and percentile for a given indicator/period.
"""

import json

from fastapi import APIRouter, HTTPException, Query, Request
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
    parsed: dict[str, object] = json.loads(geojson_str)
    return parsed


@router.get("/place/{place_id}/peers/geometry")
async def get_peer_geometry(
    request: Request,
    place_id: str,
    indicator: str | None = Query(default=None),
    period: str | None = Query(default=None),
) -> dict[str, object]:
    """GeoJSON FeatureCollection of peer places (same `type`, excluding
    the given place). Each feature's properties carry {id, name, value,
    percentile} where value/percentile come from a left join on
    `data.indicator_value` for the given indicator/period."""
    engine = request.app.state.engine
    async with engine.connect() as conn:
        place_row = (
            await conn.execute(
                text("SELECT type FROM geography.place WHERE id = :place_id"),
                {"place_id": place_id},
            )
        ).first()
        if place_row is None:
            raise HTTPException(status_code=404, detail="place not found")
        place_type = place_row.type

        rows = (
            await conn.execute(
                text(
                    """
                    WITH peer_values AS (
                        SELECT
                            p.id,
                            p.name,
                            iv.value
                        FROM geography.place p
                        LEFT JOIN data.indicator_value iv
                            ON iv.place_id = p.id
                            AND iv.indicator_key = :indicator
                            AND iv.period = :period
                        WHERE p.type = :place_type
                            AND p.id <> :place_id
                    ),
                    ranked AS (
                        SELECT
                            pv.*,
                            RANK() OVER (
                                ORDER BY pv.value DESC NULLS LAST
                            ) AS rank,
                            COUNT(pv.value) OVER () AS n_with_values
                        FROM peer_values pv
                    )
                    SELECT
                        r.id,
                        r.name,
                        r.value,
                        r.rank,
                        r.n_with_values,
                        ST_AsGeoJSON(ST_Simplify(p.geom, 0.005)) AS geojson
                    FROM ranked r
                    JOIN geography.place p ON p.id = r.id
                    """
                ),
                {
                    "place_id": place_id,
                    "place_type": place_type,
                    "indicator": indicator,
                    "period": period,
                },
            )
        ).all()

    features: list[dict[str, object]] = []
    for r in rows:
        geometry = _parse_geojson(r.geojson)
        percentile = _percentile_from_rank(r.rank, r.n_with_values)
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "id": r.id,
                    "name": r.name,
                    "value": float(r.value) if r.value is not None else None,
                    "percentile": percentile,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _percentile_from_rank(rank: int | None, n: int) -> float | None:
    """`(n - rank) / (n - 1) * 100`. Top = 100, bottom = 0.
    Undefined when n <= 1 or value is missing."""
    if rank is None or n is None or n <= 1:
        return None
    return (n - rank) / (n - 1) * 100.0

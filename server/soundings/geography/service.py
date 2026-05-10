"""GeographyService — internal orchestrator-facing geography API.

Resolves postcodes/names/points to canonical place rows and traverses the
place hierarchy. Built on top of `geography.*` tables and the postcodes.io
adapter.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from soundings.adapters.postcodes_io.adapter import PostcodesIoAdapter
from soundings.db.models.geography import Place, PlaceHierarchy, Postcode

POSTCODE_FRESHNESS = timedelta(days=30)


@dataclass(frozen=True)
class PlaceMatch:
    place: Place
    confidence: float


def _normalise_postcode(postcode: str) -> str:
    return postcode.replace(" ", "").upper()


class GeographyService:
    def __init__(self, engine: AsyncEngine, postcodes_io: PostcodesIoAdapter) -> None:
        self._engine = engine
        self._postcodes_io = postcodes_io

    async def find_place_by_postcode(self, postcode: str) -> dict[str, Place] | None:
        """Returns dict keyed by place type → Place, for all containing levels.

        Cache-first: hits geography.postcode if a fresh row exists, otherwise
        falls through to the postcodes.io adapter to resolve and upsert.
        """
        normalised = _normalise_postcode(postcode)
        cached = await self._read_cached_postcode(normalised)
        if cached is None:
            await self._postcodes_io.upsert_postcode(postcode)
            cached = await self._read_cached_postcode(normalised)
            if cached is None:
                return None

        place_ids = [
            pid
            for pid in (
                cached.lsoa21,
                cached.msoa21,
                cached.ltla24,
                cached.utla24,
                cached.ward24,
                cached.westminster_constituency_24,
                cached.region,
                cached.country,
            )
            if pid
        ]
        if not place_ids:
            return {}

        async with AsyncSession(self._engine) as session:
            places = (await session.scalars(select(Place).where(Place.id.in_(place_ids)))).all()
        return {p.type: p for p in places}

    async def find_place_by_name(
        self,
        query: str,
        geography_types: list[str] | None = None,
        limit: int = 5,
    ) -> list[PlaceMatch]:
        """Fuzzy place-name search via pg_trgm similarity."""
        similarity = func.similarity(Place.name, query).label("score")
        stmt = (
            select(Place, similarity)
            .where(similarity > 0.1)
            .order_by(similarity.desc())
            .limit(limit)
        )
        if geography_types:
            stmt = stmt.where(Place.type.in_(geography_types))
        async with AsyncSession(self._engine) as session:
            rows = (await session.execute(stmt)).all()
        return [PlaceMatch(place=r.Place, confidence=float(r.score)) for r in rows]

    async def find_containing_places(self, place_id: str) -> list[Place]:
        """All ancestor Places of a given place_id, via the hierarchy table."""
        stmt = (
            select(Place)
            .join(PlaceHierarchy, Place.id == PlaceHierarchy.parent_id)
            .where(PlaceHierarchy.child_id == place_id)
        )
        async with AsyncSession(self._engine) as session:
            return list((await session.scalars(stmt)).all())

    async def find_containing_places_by_point(
        self,
        lat: float,
        lng: float,
        types: list[str] | None = None,
    ) -> list[Place]:
        """Point-in-polygon containing-place lookup via PostGIS ST_Within."""
        clauses = "WHERE ST_Within(ST_SetSRID(ST_Point(:lng, :lat), 4326), geom)"
        if types:
            placeholders = ", ".join(f":t{i}" for i, _ in enumerate(types))
            clauses += f" AND type IN ({placeholders})"
        # `clauses` is built only from a fixed set of `:tN` placeholders, not user input.
        sql = f"SELECT id, type, code, name, valid_from, valid_to FROM geography.place {clauses}"  # noqa: S608
        params: dict[str, object] = {"lat": lat, "lng": lng}
        if types:
            for i, t in enumerate(types):
                params[f"t{i}"] = t
        async with AsyncSession(self._engine) as session:
            rows = (await session.execute(text(sql), params)).all()
        return [
            Place(
                id=r.id,
                type=r.type,
                code=r.code,
                name=r.name,
                valid_from=r.valid_from,
                valid_to=r.valid_to,
            )
            for r in rows
        ]

    async def _read_cached_postcode(self, normalised: str) -> Postcode | None:
        cutoff = datetime.now(tz=UTC) - POSTCODE_FRESHNESS
        async with AsyncSession(self._engine) as session:
            return (
                await session.scalars(
                    select(Postcode).where(
                        Postcode.postcode == normalised,
                        Postcode.retrieved_at >= cutoff,
                    )
                )
            ).one_or_none()

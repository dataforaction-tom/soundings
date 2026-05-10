"""GeographyService — internal orchestrator-facing geography API.

Resolves postcodes/names/points to canonical place rows and traverses the
place hierarchy. Built on top of `geography.*` tables and the postcodes.io
adapter.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from soundings.adapters.postcodes_io.adapter import PostcodesIoAdapter
from soundings.db.models.geography import Place, Postcode

POSTCODE_FRESHNESS = timedelta(days=30)


@dataclass(frozen=True)
class PlaceMatch:
    place: Place
    confidence: float


def _normalise_postcode(postcode: str) -> str:
    return postcode.replace(" ", "").upper()


class GeographyService:
    def __init__(
        self, engine: AsyncEngine, postcodes_io: PostcodesIoAdapter
    ) -> None:
        self._engine = engine
        self._postcodes_io = postcodes_io

    async def find_place_by_postcode(
        self, postcode: str
    ) -> dict[str, Place] | None:
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
            places = (
                await session.scalars(select(Place).where(Place.id.in_(place_ids)))
            ).all()
        return {p.type: p for p in places}

    async def _read_cached_postcode(self, normalised: str) -> Postcode | None:
        cutoff = datetime.now(tz=timezone.utc) - POSTCODE_FRESHNESS
        async with AsyncSession(self._engine) as session:
            return (
                await session.scalars(
                    select(Postcode).where(
                        Postcode.postcode == normalised,
                        Postcode.retrieved_at >= cutoff,
                    )
                )
            ).one_or_none()

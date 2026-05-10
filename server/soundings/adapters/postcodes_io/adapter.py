"""postcodes.io passthrough adapter.

Resolves a UK postcode to the canonical Soundings place IDs at every
geography level v1 cares about. Cached per-postcode in `cache.source_cache`
with the source's TTL (default 30 days for postcodes.io).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert

from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.db.models.geography import Postcode

API_HOST = "https://api.postcodes.io"


@dataclass
class PostcodeLookup:
    postcode: str
    lsoa21: str | None
    msoa21: str | None
    ltla24: str | None
    utla24: str | None
    ward24: str | None
    westminster_constituency_24: str | None
    region: str | None
    country: str | None


def _normalise_postcode(postcode: str) -> str:
    return postcode.replace(" ", "").upper()


def _qualified(place_type: str, code: str | None) -> str | None:
    return f"{place_type}:{code}" if code else None


class PostcodesIoAdapter(PassthroughAdapter):
    source_id = "postcodes.io"

    async def lookup(self, postcode: str) -> PostcodeLookup | None:
        cache_key = _normalise_postcode(postcode)
        payload = await self._fetch_cached(cache_key)
        if payload is None:
            return None
        return self._map_to_lookup(postcode, payload)

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any | None:
        response = await client.get(f"{API_HOST}/postcodes/{cache_key}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def upsert_postcode(self, postcode: str) -> PostcodeLookup | None:
        """Look up the postcode and upsert the result into geography.postcode."""
        result = await self.lookup(postcode)
        if result is None:
            return None
        normalised = _normalise_postcode(postcode)
        async with self._cache._engine.begin() as conn:
            stmt = insert(Postcode).values(
                postcode=normalised,
                lsoa21=result.lsoa21,
                msoa21=result.msoa21,
                ltla24=result.ltla24,
                utla24=result.utla24,
                ward24=result.ward24,
                westminster_constituency_24=result.westminster_constituency_24,
                region=result.region,
                country=result.country,
                retrieved_at=datetime.now(tz=UTC),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[Postcode.postcode],
                set_={
                    "lsoa21": stmt.excluded.lsoa21,
                    "msoa21": stmt.excluded.msoa21,
                    "ltla24": stmt.excluded.ltla24,
                    "utla24": stmt.excluded.utla24,
                    "ward24": stmt.excluded.ward24,
                    "westminster_constituency_24": stmt.excluded.westminster_constituency_24,
                    "region": stmt.excluded.region,
                    "country": stmt.excluded.country,
                    "retrieved_at": stmt.excluded.retrieved_at,
                },
            )
            await conn.execute(stmt)
        result.postcode = normalised
        return result

    @staticmethod
    def _map_to_lookup(postcode: str, payload: dict[str, Any]) -> PostcodeLookup:
        result = payload.get("result", {})
        codes = result.get("codes", {}) if isinstance(result, dict) else {}
        return PostcodeLookup(
            postcode=postcode,
            lsoa21=_qualified("lsoa21", codes.get("lsoa")),
            msoa21=_qualified("msoa21", codes.get("msoa")),
            ltla24=_qualified("ltla24", codes.get("admin_district")),
            utla24=_qualified("utla24", codes.get("admin_county") or codes.get("admin_district")),
            ward24=_qualified("ward24", codes.get("admin_ward")),
            westminster_constituency_24=_qualified(
                "westminster_constituency_24",
                codes.get("parliamentary_constituency_2024")
                or codes.get("parliamentary_constituency"),
            ),
            region=_qualified("region", codes.get("region")),
            country=_qualified("country", codes.get("country")),
        )

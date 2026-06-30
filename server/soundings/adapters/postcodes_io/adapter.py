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

    def place_id_references(self) -> list[str]:
        return [
            v
            for v in (
                self.lsoa21,
                self.msoa21,
                self.ltla24,
                self.utla24,
                self.ward24,
                self.westminster_constituency_24,
                self.region,
                self.country,
            )
            if v is not None
        ]

    def with_fk_safe(self, valid_place_ids: set[str]) -> "PostcodeLookup":
        """Return a copy with any place_id reference NULLed out unless it
        exists in `valid_place_ids`. Used by `bulk_upsert` so partial
        geography seeds don't FK-fail the postcode upsert."""

        def keep(value: str | None) -> str | None:
            if value is None:
                return None
            return value if value in valid_place_ids else None

        return PostcodeLookup(
            postcode=self.postcode,
            lsoa21=keep(self.lsoa21),
            msoa21=keep(self.msoa21),
            ltla24=keep(self.ltla24),
            utla24=keep(self.utla24),
            ward24=keep(self.ward24),
            westminster_constituency_24=keep(self.westminster_constituency_24),
            region=keep(self.region),
            country=keep(self.country),
        )


def _normalise_postcode(postcode: str) -> str:
    return postcode.replace(" ", "").upper()


def _qualified(place_type: str, code: str | None) -> str | None:
    return f"{place_type}:{code}" if code else None


def _chunked(seq: list[str], n: int) -> list[list[str]]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def _upsert_postcode_stmt(normalised_postcode: str, lookup: PostcodeLookup) -> Any:
    stmt = insert(Postcode).values(
        postcode=normalised_postcode,
        lsoa21=lookup.lsoa21,
        msoa21=lookup.msoa21,
        ltla24=lookup.ltla24,
        utla24=lookup.utla24,
        ward24=lookup.ward24,
        westminster_constituency_24=lookup.westminster_constituency_24,
        region=lookup.region,
        country=lookup.country,
        retrieved_at=datetime.now(tz=UTC),
    )
    return stmt.on_conflict_do_update(
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
        """Look up the postcode and upsert the result into geography.postcode.

        Applies the same FK-tolerant filtering as `bulk_upsert`: a partial
        geography spine (e.g. this project drops the MSOA layer) means some
        place references have no `geography.place` row, so NULL those out
        rather than letting the upsert FK-fail.
        """
        result = await self.lookup(postcode)
        if result is None:
            return None
        normalised = _normalise_postcode(postcode)
        valid_place_ids = await self._fetch_known_place_ids(set(result.place_id_references()))
        filtered = result.with_fk_safe(valid_place_ids)
        async with self._engine.begin() as conn:
            await conn.execute(_upsert_postcode_stmt(normalised, filtered))
        filtered.postcode = normalised
        return filtered

    async def bulk_upsert(self, postcodes: list[str]) -> dict[str, PostcodeLookup | None]:
        """Resolve up to N postcodes via postcodes.io's bulk endpoint.

        Batches 100 per POST (the API limit), upserts each resolved row
        into `geography.postcode`. Returns a dict keyed by the *original*
        (un-normalised) postcode string so callers can match back to
        their input.

        Unknown postcodes map to None entries; the resolver
        (`charity_commission.mapping.resolve_postcodes_to_ltlas`)
        decides what to do with them. Does NOT route through
        `cache.source_cache` — `geography.postcode` IS the durable cache
        for postcode lookups, with a much longer effective lifetime than
        the source_cache TTL.
        """
        if not postcodes:
            return {}

        all_lookups: dict[str, PostcodeLookup | None] = {}
        original_by_norm: dict[str, str] = {}
        for batch in _chunked(postcodes, 100):
            for p in batch:
                original_by_norm[_normalise_postcode(p)] = p
            payload = await self._post_bulk([_normalise_postcode(p) for p in batch])
            for entry in payload.get("result") or []:
                query = entry.get("query")
                inner = entry.get("result")
                if query is None:
                    continue
                norm = _normalise_postcode(query)
                if inner is None:
                    all_lookups[norm] = None
                    continue
                all_lookups[norm] = self._map_to_lookup(query, {"result": inner})

        # FK-filter: bulk upsert tolerates partial geography spines —
        # NULL out any place_id reference whose `geography.place` row
        # isn't seeded. CC only cares about ltla24; the others
        # populate when the full geography seed runs.
        valid_place_ids = await self._fetch_known_place_ids(
            {
                pid
                for lookup in all_lookups.values()
                if lookup is not None
                for pid in lookup.place_id_references()
            }
        )

        results: dict[str, PostcodeLookup | None] = {}
        async with self._engine.begin() as conn:
            for norm, lookup in all_lookups.items():
                original = original_by_norm.get(norm)
                if original is None:
                    continue
                if lookup is None:
                    results[original] = None
                    continue
                filtered = lookup.with_fk_safe(valid_place_ids)
                await conn.execute(_upsert_postcode_stmt(norm, filtered))
                results[original] = filtered
        return results

    async def _fetch_known_place_ids(self, candidate_ids: set[str]) -> set[str]:
        if not candidate_ids:
            return set()
        from sqlalchemy import text as _text

        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    _text("SELECT id FROM geography.place WHERE id = ANY(:ids)"),
                    {"ids": list(candidate_ids)},
                )
            ).all()
        return {row.id for row in rows}

    async def _post_bulk(self, postcodes: list[str]) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            async with self._limiter:
                response = await client.post(f"{API_HOST}/postcodes", json={"postcodes": postcodes})
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
            return payload
        finally:
            if self._client is None:
                await client.aclose()

    @staticmethod
    def _map_to_lookup(postcode: str | None, payload: dict[str, Any]) -> PostcodeLookup:
        result = payload.get("result", {})
        codes = result.get("codes", {}) if isinstance(result, dict) else {}
        return PostcodeLookup(
            postcode=postcode or "",
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

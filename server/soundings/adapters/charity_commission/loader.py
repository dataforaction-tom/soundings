"""CharityCommissionLoader — writes the monthly CC bulk register into
`data.organisation` + `data.organisation_operates_in`.

The bulk client streams active charities (status='Registered'); we
batch-resolve their postcodes via the postcodes.io bulk endpoint
(`charity_commission.mapping.resolve_postcodes_to_ltlas`), build
organisation rows, and upsert in chunks. Idempotent: re-running
against the same bulk pull updates `retrieved_at` but doesn't
duplicate rows.

Task 7 layers on top of this to write the
`civil_society.active_charities_count` + `_per_10k` indicator
aggregates at the end of each load.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.base import LoaderAdapter, LoaderResult
from soundings.adapters.charity_commission.client import CharityCommissionBulkClient
from soundings.adapters.charity_commission.mapping import resolve_postcodes_to_ltlas
from soundings.adapters.postcodes_io.adapter import PostcodesIoAdapter
from soundings.db.models.data import Organisation, OrganisationOperatesIn

SOURCE_ID = "charity_commission"
ORG_INSERT_CHUNK = 1000
POSTCODES_IO_TTL_HOURS = 720  # 30 days, matches sources.yaml


class CharityCommissionLoader(LoaderAdapter):
    source_id = SOURCE_ID

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        bulk_client: CharityCommissionBulkClient | None = None,
        postcodes_io: PostcodesIoAdapter | None = None,
    ) -> None:
        super().__init__(engine)
        self._bulk_client = bulk_client or CharityCommissionBulkClient()
        self._postcodes_io = postcodes_io or PostcodesIoAdapter(
            engine, ttl=timedelta(hours=POSTCODES_IO_TTL_HOURS)
        )

    async def load(self, run_id: str | None = None) -> LoaderResult:
        # Pass 1: collect all rows + postcodes. ~50MB in memory at 220k
        # rows — acceptable for v1. Future optimisation could two-pass
        # the bulk download to avoid the in-memory list.
        rows: list[dict[str, Any]] = []
        async for charity in self._bulk_client.iter_active_charities():
            rows.append(charity)

        # Pass 2: batch-resolve postcodes (the resolver short-circuits
        # any postcode already cached in geography.postcode, so monthly
        # re-loads against a warm cache hit postcodes.io zero times).
        postcodes = [r["postcode"] for r in rows if r.get("postcode")]
        resolved = await resolve_postcodes_to_ltlas(self._postcodes_io, postcodes)

        # Pass 3: materialise + chunked upsert.
        retrieved_at = datetime.now(tz=UTC)
        org_rows = self._build_org_rows(rows, resolved, retrieved_at)
        operates_in_rows = self._build_operates_in_rows(org_rows)

        await self._upsert_organisations(org_rows)
        await self._upsert_operates_in(operates_in_rows)

        unresolved = sum(1 for r in rows if not resolved.get(r.get("postcode", "")))
        notes: str | None = None
        if unresolved:
            notes = (
                f"{unresolved} charities with unresolved postcodes — "
                "registered_address_place_id null"
            )
        return LoaderResult(rows_written=len(org_rows), notes=notes)

    @staticmethod
    def _build_org_rows(
        rows: list[dict[str, Any]],
        resolved: dict[str, str | None],
        retrieved_at: datetime,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for charity in rows:
            postcode = charity.get("postcode") or ""
            place_id = resolved.get(postcode)
            org_id = f"charity_commission:{charity['registration_number']}"
            out.append(
                {
                    "id": org_id,
                    "name": charity["name"],
                    "classification": charity.get("classification") or [],
                    "registered_address_place_id": place_id,
                    "source_id": SOURCE_ID,
                    "retrieved_at": retrieved_at,
                    "raw": charity,
                }
            )
        return out

    @staticmethod
    def _build_operates_in_rows(org_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {"organisation_id": row["id"], "place_id": row["registered_address_place_id"]}
            for row in org_rows
            if row["registered_address_place_id"] is not None
        ]

    async def _upsert_organisations(self, org_rows: list[dict[str, Any]]) -> None:
        if not org_rows:
            return
        async with self._engine.begin() as conn:
            for chunk in _chunked(org_rows, ORG_INSERT_CHUNK):
                stmt = insert(Organisation).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=[Organisation.id],
                    set_={
                        "name": stmt.excluded.name,
                        "classification": stmt.excluded.classification,
                        "registered_address_place_id": stmt.excluded.registered_address_place_id,
                        "retrieved_at": stmt.excluded.retrieved_at,
                        "raw": stmt.excluded.raw,
                    },
                )
                await conn.execute(stmt)

    async def _upsert_operates_in(self, operates_in_rows: list[dict[str, str]]) -> None:
        if not operates_in_rows:
            return
        async with self._engine.begin() as conn:
            for chunk in _chunked(operates_in_rows, ORG_INSERT_CHUNK):
                stmt = insert(OrganisationOperatesIn).values(chunk)
                stmt = stmt.on_conflict_do_nothing()
                await conn.execute(stmt)


def _chunked(seq: list[Any], n: int) -> list[list[Any]]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]

"""NsplLoader — populates geography.postcode from the ONS NSPL bulk product.

Streams the NSPL CSV, maps each row's statutory-geography codes to our
prefixed place IDs (`E06000047` -> `ltla24:E06000047`), nulls any code not
present in geography.place (an FK guard, so a boundary-vintage mismatch or
an unseeded ward degrades to NULL rather than an FK violation), and upserts
in batches. After the upsert, utla24 — which NSPL has no field for — is
derived by joining each postcode's ltla24 to its parent UTLA in
geography.place_hierarchy.

See docs/superpowers/specs/2026-07-07-nspl-loader-design.md.
"""

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.base import LoaderAdapter, LoaderResult
from soundings.adapters.ons_nspl.client import NsplBulkClient
from soundings.adapters.postcodes_io.adapter import _normalise_postcode
from soundings.core.config import get_settings

SOURCE_ID = "ons.nspl"
BATCH_SIZE = 10_000

# NSPL column -> (our geography.postcode column, place-id type prefix).
# utla24 is derived post-load (NSPL has no UTLA field), so it is not here.
_COLUMN_MAP: list[tuple[str, str, str]] = [
    ("lsoa21", "lsoa21", "lsoa21"),
    ("msoa21", "msoa21", "msoa21"),
    ("laua", "ltla24", "ltla24"),
    ("ward", "ward24", "ward24"),
    ("pcon", "westminster_constituency_24", "westminster_constituency_24"),
    ("rgn", "region", "region"),
    ("ctry", "country", "country"),
]

_UPSERT_SQL = text(
    "INSERT INTO geography.postcode "
    "(postcode, lsoa21, msoa21, ltla24, ward24, "
    " westminster_constituency_24, region, country, retrieved_at) "
    "VALUES (:postcode, :lsoa21, :msoa21, :ltla24, :ward24, "
    "        :westminster_constituency_24, :region, :country, :retrieved_at) "
    "ON CONFLICT (postcode) DO UPDATE SET "
    "  lsoa21 = EXCLUDED.lsoa21, msoa21 = EXCLUDED.msoa21, "
    "  ltla24 = EXCLUDED.ltla24, ward24 = EXCLUDED.ward24, "
    "  westminster_constituency_24 = EXCLUDED.westminster_constituency_24, "
    "  region = EXCLUDED.region, country = EXCLUDED.country, "
    "  retrieved_at = EXCLUDED.retrieved_at"
)

# Derive utla24 from each postcode's ltla24 via the place hierarchy.
_DERIVE_UTLA_SQL = text(
    "UPDATE geography.postcode p "
    "SET utla24 = h.parent_id "
    "FROM geography.place_hierarchy h "
    "WHERE h.child_id = p.ltla24 "
    "  AND h.parent_id LIKE 'utla24:%' "
    "  AND p.ltla24 IS NOT NULL"
)


class NsplLoader(LoaderAdapter):
    source_id = SOURCE_ID

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        client: NsplBulkClient | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(engine)
        self._client = client
        self._url = url or get_settings().nspl_url

    async def load(self, run_id: str | None = None) -> LoaderResult:
        client = self._client or NsplBulkClient(url=self._url)
        valid_ids = await self._valid_place_ids()
        retrieved_at = datetime.now(tz=UTC)

        total = 0
        batch: list[dict[str, object]] = []
        async for raw in client.iter_rows():
            mapped = _map_row(raw, valid_ids, retrieved_at)
            if mapped is None:
                continue
            batch.append(mapped)
            if len(batch) >= BATCH_SIZE:
                await self._upsert(batch)
                total += len(batch)
                batch = []
        if batch:
            await self._upsert(batch)
            total += len(batch)

        derived = await self._derive_utla()
        return LoaderResult(
            rows_written=total,
            notes=f"{derived} postcodes assigned a utla24 via place_hierarchy",
        )

    async def _valid_place_ids(self) -> set[str]:
        async with self._engine.connect() as conn:
            rows = (await conn.execute(text("SELECT id FROM geography.place"))).all()
        return {r.id for r in rows}

    async def _upsert(self, batch: list[dict[str, object]]) -> None:
        # Small, bounded transactions — 2.7M rows in ~10k batches.
        async with self._engine.begin() as conn:
            await conn.execute(_UPSERT_SQL, batch)

    async def _derive_utla(self) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(_DERIVE_UTLA_SQL)
        return result.rowcount or 0


def _map_row(
    raw: dict[str, str],
    valid_ids: set[str],
    retrieved_at: datetime,
) -> dict[str, object] | None:
    """Map one NSPL row to a geography.postcode upsert dict, nulling any
    geography code not present in `valid_ids` (the FK guard). Returns None
    for rows with no usable postcode."""
    pcds = (raw.get("pcds") or "").strip()
    if not pcds:
        return None
    postcode = _normalise_postcode(pcds)
    if not postcode:
        return None

    mapped: dict[str, object] = {"postcode": postcode, "retrieved_at": retrieved_at}
    for nspl_col, our_col, prefix in _COLUMN_MAP:
        code = (raw.get(nspl_col) or "").strip()
        place_id = f"{prefix}:{code}" if code else None
        mapped[our_col] = place_id if (place_id and place_id in valid_ids) else None
    return mapped

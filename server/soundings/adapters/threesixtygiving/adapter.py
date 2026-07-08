"""ThreeSixtyGivingAdapter — passthrough over the 360G Datastore API.

The 360G API is org-centric (no place-based search). The adapter
composes place-level aggregates by fanning out across CC charities
registered in the queried place — those live in `data.organisation`
(populated by the Phase 4 Block A CC loader).

Indicators (catalogue keys):
- `civil_society.grants_in_last_12m_total` — sum of GBP grants
  received by charities registered in the place, awarded in the last
  12 months.
- `civil_society.grants_in_last_12m_count` — count of those grants.

Optimisations:
- `get_org_aggregate` returns `latest_grant_date` for the org. If
  that's older than the 12m window, we skip the paginated
  `iter_grants_received` call entirely (saves ~50ms × hundreds of
  orgs per LTLA).
- Per-place aggregate cached for 7 days (`cache.source_cache`).
- Per-org grants list cached for 7 days too — so different LTLAs
  that share a charity (rare; charities have one registered LTLA)
  reuse the fetch, and re-runs of the same LTLA after pre-warm hit
  cache.

`recent_grants(place_id, limit)` is exposed for Block D's
`find_organisations_in_place` tool — same fan-out, sorted by
awardDate desc, top N.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.adapters.threesixtygiving.client import (
    OrgAggregate,
    ThreeSixtyGivingClient,
)
from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.organisation import GrantRef

SOURCE_ID = "threesixtygiving"
DEFAULT_TTL = timedelta(days=7)
LAST_12M_DAYS = 365
INDICATOR_TOTAL = "civil_society.grants_in_last_12m_total"
INDICATOR_COUNT = "civil_society.grants_in_last_12m_count"


class ThreeSixtyGivingAdapter(PassthroughAdapter):
    source_id = SOURCE_ID

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        ttl: timedelta = DEFAULT_TTL,
        threesixtygiving_client: ThreeSixtyGivingClient | None = None,
        http_client: httpx.AsyncClient | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        super().__init__(engine, ttl=ttl, http_client=http_client)
        self._tsg = threesixtygiving_client or ThreeSixtyGivingClient(http_client=http_client)
        self._now = now

    # ----- IndicatorValue path --------------------------------------------

    async def fetch_indicator(
        self,
        indicator_key: str,
        place_id: str,
        period: str | None,
    ) -> IndicatorValue | None:
        if indicator_key not in (INDICATOR_TOTAL, INDICATOR_COUNT):
            return None

        grants = await self._fetch_grants_for_place(place_id)

        if indicator_key == INDICATOR_TOTAL:
            value = sum(g["amount"] for g in grants)
            unit = "GBP"
        else:
            value = float(len(grants))
            unit = "grants"

        caveats: list[str] = []
        if not await self._has_charities_for_place(place_id):
            caveats.append(
                "no charities registered for this place in data.organisation — "
                "CC loader hasn't run for this LTLA yet, or the place lies "
                "outside England and Wales"
            )

        source_ref = await self._build_source_ref(retrieved_at=self._now(), cache_status="cached")
        return IndicatorValue(
            place_id=place_id,
            indicator=indicator_key,
            value=value,
            unit=unit,
            period=self._now().strftime("%Y-%m"),
            source=source_ref,
            caveats=caveats,
            confidence="official",
        )

    # ----- Block D helper -------------------------------------------------

    async def recent_grants(self, place_id: str, *, limit: int = 3) -> list[GrantRef]:
        grants = await self._fetch_grants_for_place(place_id)
        grants_sorted = sorted(grants, key=lambda g: g["date"], reverse=True)
        source_ref = await self._build_source_ref(retrieved_at=self._now(), cache_status="cached")
        return [
            GrantRef(
                funder=g["funder"],
                amount=g["amount"],
                currency="GBP",
                date=g["date"],
                purpose=g.get("purpose"),
                source=source_ref,
            )
            for g in grants_sorted[:limit]
        ]

    async def recent_grants_for_org(self, org_id: str, *, limit: int = 3) -> list[GrantRef]:
        """Per-org slice of the same fan-out, for `find_organisations_in_place`.

        Accepts either a CC-prefixed id (`charity_commission:1234`) or a 360G
        org id (`GB-CHC-1234`); converts as needed. Returns the org's most
        recent grants from `_cached_org_grants`.
        """
        tsg_org_id = _cc_to_tsg_org_id(org_id)
        grants = await self._cached_org_grants(tsg_org_id)
        grants_sorted = sorted(grants, key=lambda g: g["date"], reverse=True)
        source_ref = await self._build_source_ref(retrieved_at=self._now(), cache_status="cached")
        return [
            GrantRef(
                funder=g["funder"],
                amount=g["amount"],
                currency="GBP",
                date=g["date"],
                purpose=g.get("purpose"),
                source=source_ref,
            )
            for g in grants_sorted[:limit]
        ]

    # ----- Core fan-out ---------------------------------------------------

    async def _fetch_all_grants_for_place(self, place_id: str) -> list[dict[str, Any]]:
        """Returns ALL grants (full history) for charities registered in place_id.

        Unlike _fetch_grants_for_place which filters to the last 12 months,
        this returns every grant in the per-org caches. Used for temporal
        aggregation (grants by year). Per-org caches are already populated
        by the pre-warmer; a cold place will fan out (slow).
        """
        place_cache_key = f"360g:place_all_grants:{place_id}"
        cached = await self._cache.get(self.source_id, place_cache_key)
        if cached is not None and isinstance(cached, list):
            for g in cached:
                g["date_obj"] = _parse_iso_date(g["date"])
            return cached

        org_ids = await self._cc_org_ids_for_place(place_id)
        if not org_ids:
            empty: list[dict[str, Any]] = []
            await self._cache.put(self.source_id, place_cache_key, empty, ttl=self._ttl)
            return empty

        all_grants: list[dict[str, Any]] = []
        for org_id in org_ids:
            tsg_org_id = _cc_to_tsg_org_id(org_id)
            aggregate = await self._cached_org_aggregate(tsg_org_id)
            if aggregate is None:
                continue
            # Skip orgs with no grants at all
            if not aggregate.latest_grant_date and not aggregate.earliest_grant_date:
                continue
            org_grants = await self._cached_org_grants(tsg_org_id)
            all_grants.extend(org_grants)

        compact = [{k: v for k, v in g.items() if k != "date_obj"} for g in all_grants]
        await self._cache.put(self.source_id, place_cache_key, compact, ttl=self._ttl)
        for g in compact:
            g["date_obj"] = _parse_iso_date(g["date"])
        return compact

    async def _fetch_grants_for_place(self, place_id: str) -> list[dict[str, Any]]:
        """Returns a list of {date, amount, funder, purpose} for every
        grant in the last 12 months received by a charity registered in
        `place_id`.

        Per-place cached for 7 days; per-org grants cached for 7 days
        underneath. The first call for a cold place fans out across all
        its charities; subsequent calls return from the per-place cache.
        """
        place_cache_key = f"360g:place_grants:{place_id}"
        cached = await self._cache.get(self.source_id, place_cache_key)
        if cached is not None and isinstance(cached, list):
            return cached

        org_ids = await self._cc_org_ids_for_place(place_id)
        if not org_ids:
            empty: list[dict[str, Any]] = []
            await self._cache.put(self.source_id, place_cache_key, empty, ttl=self._ttl)
            return empty

        cutoff = self._now() - timedelta(days=LAST_12M_DAYS)
        all_grants: list[dict[str, Any]] = []

        for org_id in org_ids:
            tsg_org_id = _cc_to_tsg_org_id(org_id)
            aggregate = await self._cached_org_aggregate(tsg_org_id)
            # Optimisation: skip orgs whose latest grant predates the
            # window. The aggregate is a single-call surface that tells
            # us this without paginating.
            if aggregate is None:
                continue
            if (
                aggregate.latest_grant_date
                and _parse_iso_date(aggregate.latest_grant_date) < cutoff.date()
            ):
                continue

            org_grants = await self._cached_org_grants(tsg_org_id)
            for grant in org_grants:
                if grant["date_obj"] >= cutoff.date():
                    all_grants.append(grant)

        # Strip the parsed-date helper before caching (JSON-serialisable).
        compact = [{k: v for k, v in g.items() if k != "date_obj"} for g in all_grants]
        await self._cache.put(self.source_id, place_cache_key, compact, ttl=self._ttl)
        # Hydrate parsed dates for downstream sorting (recent_grants needs
        # them; the indicator path only sums + counts).
        for g in compact:
            g["date_obj"] = _parse_iso_date(g["date"])
        return compact

    async def _cached_org_aggregate(self, tsg_org_id: str) -> OrgAggregate | None:
        cache_key = f"360g:agg:{tsg_org_id}"
        cached = await self._cache.get(self.source_id, cache_key)
        if cached is not None:
            if cached == "__none__":
                return None
            if isinstance(cached, dict):
                return OrgAggregate(**cached)
        aggregate = await self._tsg.get_org_aggregate(tsg_org_id)
        if aggregate is None:
            await self._cache.put(self.source_id, cache_key, "__none__", ttl=self._ttl)
            return None
        await self._cache.put(self.source_id, cache_key, aggregate.__dict__, ttl=self._ttl)
        return aggregate

    async def _cached_org_grants(self, tsg_org_id: str) -> list[dict[str, Any]]:
        cache_key = f"360g:grants:{tsg_org_id}"
        cached = await self._cache.get(self.source_id, cache_key)
        if cached is not None and isinstance(cached, list):
            for g in cached:
                g["date_obj"] = _parse_iso_date(g["date"])
            return cached

        grants: list[dict[str, Any]] = []
        async for raw in self._tsg.iter_grants_received(tsg_org_id):
            grant = _materialise_grant(raw)
            if grant is None:
                continue
            grants.append(grant)

        compact = [{k: v for k, v in g.items() if k != "date_obj"} for g in grants]
        await self._cache.put(self.source_id, cache_key, compact, ttl=self._ttl)
        for g in compact:
            g["date_obj"] = _parse_iso_date(g["date"])
        return compact

    # ----- Lookups --------------------------------------------------------

    async def _cc_org_ids_for_place(self, place_id: str) -> list[str]:
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id FROM data.organisation "
                        "WHERE source_id = 'charity_commission' "
                        "AND registered_address_place_id = :pid "
                        "ORDER BY id"
                    ),
                    {"pid": place_id},
                )
            ).all()
        return [r.id for r in rows]

    async def _has_charities_for_place(self, place_id: str) -> bool:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM data.organisation "
                        "WHERE source_id = 'charity_commission' "
                        "AND registered_address_place_id = :pid "
                        "LIMIT 1"
                    ),
                    {"pid": place_id},
                )
            ).first()
        return row is not None

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any:
        del client, cache_key
        raise NotImplementedError("ThreeSixtyGivingAdapter routes via fetch_indicator override")

    # ----- pre_warmer hook ------------------------------------------------

    async def pre_warm_for_places(self, place_ids: list[str]) -> None:
        """Walk every supplied LTLA, fan out + populate
        `360g:place_grants:{place_id}` + the underlying per-org caches.
        Driven by the `pre_warmer` daemon (Block 0) on the source's
        `refresh_cadence` cron — weekly per sources.yaml.

        Pre-warming at the per-place level means user-facing
        `fetch_indicator` calls always hit a warm cache for the LTLA
        universe we know about. Cold misses only happen for newly-
        added LTLAs between warmer runs.
        """
        import logging

        log = logging.getLogger(__name__)
        for place_id in place_ids:
            try:
                await self._fetch_grants_for_place(place_id)
            except Exception:
                # Best-effort — `safe_pre_warm` wraps the outer call,
                # but log per-place failures here so one bad LTLA
                # doesn't blank the rest of the warm pass.
                log.exception("360G pre_warm failed for place_id=%s", place_id)


# --- helpers ----------------------------------------------------------------


def _cc_to_tsg_org_id(cc_id: str) -> str:
    """data.organisation `charity_commission:1234` → 360G `GB-CHC-1234`."""
    if cc_id.startswith("charity_commission:"):
        return "GB-CHC-" + cc_id.split(":", 1)[1]
    return cc_id


def _materialise_grant(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten a 360G grant payload into the shape we cache + return.

    Only GBP grants are counted; non-GBP grants are dropped (the
    `civil_society.grants_in_last_12m_total` indicator's unit is
    fixed at GBP per the catalogue)."""
    data = raw.get("data") or {}
    if data.get("currency") != "GBP":
        return None
    award_date = data.get("awardDate")
    amount = data.get("amountAwarded")
    if not award_date or amount is None:
        return None
    iso_date = str(award_date)[:10]  # strip time component if present
    try:
        date_obj = _parse_iso_date(iso_date)
    except ValueError:
        return None
    funders = data.get("fundingOrganization") or []
    funder_name = ""
    if funders and isinstance(funders, list):
        first = funders[0]
        if isinstance(first, dict):
            funder_name = str(first.get("name") or first.get("id") or "")
    return {
        "date": iso_date,
        "date_obj": date_obj,
        "amount": float(amount),
        "funder": funder_name,
        "purpose": data.get("description") or data.get("title"),
    }


def _parse_iso_date(iso: str) -> Any:
    from datetime import date

    return date.fromisoformat(iso[:10])

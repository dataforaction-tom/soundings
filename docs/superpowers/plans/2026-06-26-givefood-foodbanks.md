# Give Food Food-Bank Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Give Food the authoritative source for food-bank counts and map locations, replacing OSM for that one amenity.

**Architecture:** A new `givefood` passthrough adapter fetches Give Food's single daily food-bank dump (cached 24h) and matches each location to a place by point-in-polygon on its `lat_lng` (LSOA-code fallback). The `infrastructure.food_banks_count` indicator is re-pointed from OSM to Give Food, and the `/amenities/geometry` endpoint becomes source-aware so food banks pull from Give Food while other amenities stay on OSM.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy(async) / PostGIS / pydantic; httpx; pytest (`integration` marker needs the Docker Postgres on `localhost:5433`).

## Global Constraints

- Conventional Commits (`feat`, `fix`, `test`, `docs`, `chore`); subject ≤72 chars; never include Claude/AI attribution.
- TDD: failing test → minimal code → green → commit. Work on branch `feat/givefood-foodbanks` (already checked out); never commit to `main`.
- Never `--no-verify`; pre-commit runs ruff + ruff-format (Python) — pre-format changed files with `cd server && uv run ruff format <files>`.
- Integration tests MUST use the test DB, never the dev DB. Prefix every integration run with:
  `DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test"`
- Unit tests (no DB): `cd server && uv run pytest -m "not live and not integration" …`
- Give Food terms: send a `User-Agent` identifying us; attribution is satisfied by the catalogue source row's `publisher_url` rendered in the UI sources footer.
- A transport/parse failure must propagate (→ caveat / block error), never be cached as zero — mirroring the OSM `OverpassUnavailableError` discipline.
- Coordinate order in GeoJSON is `[lng, lat]` (GeoJSON order), not `[lat, lng]`.
- Cache rows are keyed by `(source_id, cache_key)`; `self._cache.get(self.source_id, key)` / `self._cache.put(self.source_id, key, value, ttl=self._ttl)`.

**Dump record shape** (after trimming, produced by Task 1, consumed by Tasks 2-3):
`{"lat": float|None, "lng": float|None, "postcode": str|None, "lsoa": str|None, "name": str, "org": str|None}`

---

### Task 1: GiveFoodClient — fetch + trim the dump

**Files:**
- Create: `server/soundings/adapters/givefood/__init__.py` (empty)
- Create: `server/soundings/adapters/givefood/client.py`
- Test: `server/tests/test_givefood_client.py`

**Interfaces:**
- Produces: `GiveFoodClient(http_client: httpx.AsyncClient | None = None)` with
  `async fetch_foodbanks() -> list[dict]` returning trimmed records of the shape in Global Constraints; module constants `DUMP_URL`, `GIVEFOOD_HEADERS`; exception `GiveFoodUnavailableError(RuntimeError)`.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_givefood_client.py`:

```python
"""Unit tests for GiveFoodClient (mock transport)."""

import httpx
import pytest

from soundings.adapters.givefood.client import (
    DUMP_URL,
    GiveFoodClient,
    GiveFoodUnavailableError,
)


def _dump_payload() -> list[dict]:
    return [
        {
            "organisation_name": "County Durham",
            "location_name": "Annfield Plain",
            "lat_lng": "54.8588523,-1.7377999",
            "postcode": "DH9 7SY",
            "lsoa": "E01020700",
        },
        {
            "organisation_name": "Solo Org",
            "location_name": "",  # falls back to organisation_name
            "lat_lng": "",  # missing coords -> lat/lng None, lsoa retained
            "postcode": "AB1 2CD",
            "lsoa": "E01099999",
        },
    ]


async def test_fetch_foodbanks_trims_and_parses() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["user_agent"] = request.headers.get("user-agent", "")
        return httpx.Response(200, json=_dump_payload())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GiveFoodClient(http_client=http)
        rows = await client.fetch_foodbanks()

    assert DUMP_URL in str(captured["url"])
    assert "Soundings" in str(captured["user_agent"])
    assert len(rows) == 2
    assert rows[0] == {
        "lat": 54.8588523,
        "lng": -1.7377999,
        "postcode": "DH9 7SY",
        "lsoa": "E01020700",
        "name": "Annfield Plain",
        "org": "County Durham",
    }
    # blank location_name falls back to organisation_name; bad lat_lng -> None
    assert rows[1]["name"] == "Solo Org"
    assert rows[1]["lat"] is None and rows[1]["lng"] is None
    assert rows[1]["lsoa"] == "E01099999"


async def test_fetch_foodbanks_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503, text="unavailable")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GiveFoodClient(http_client=http)
        with pytest.raises(GiveFoodUnavailableError):
            await client.fetch_foodbanks()


async def test_fetch_foodbanks_raises_on_non_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"unexpected": "shape"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = GiveFoodClient(http_client=http)
        with pytest.raises(GiveFoodUnavailableError):
            await client.fetch_foodbanks()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_givefood_client.py -v`
Expected: FAIL — `ModuleNotFoundError: soundings.adapters.givefood.client`.

- [ ] **Step 3: Implement the client**

Create `server/soundings/adapters/givefood/__init__.py` (empty file).

Create `server/soundings/adapters/givefood/client.py`:

```python
"""Async HTTP client for the Give Food food-bank dump.

One endpoint: the daily JSON dump of all UK food-bank locations. Each row is
trimmed to the fields Soundings uses. Identifies itself via a User-Agent per
Give Food's terms.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

DUMP_URL = "https://www.givefood.org.uk/dumps/foodbanks/json/latest/"
GIVEFOOD_HEADERS = {
    "User-Agent": "Soundings/1.0 (open insight commons; +https://github.com/dataforaction/soundings)",
    "Accept": "application/json",
}


class GiveFoodUnavailableError(RuntimeError):
    """Raised when the Give Food dump cannot be fetched or parsed.

    Distinguishes a transport/parse failure (which must surface as a caveat)
    from a genuine empty result, so the adapter never caches a fabricated 0.
    """


def _trim(row: dict[str, Any]) -> dict[str, Any]:
    """Reduce a dump row to the fields Soundings uses; parse `lat_lng`."""
    lat: float | None = None
    lng: float | None = None
    lat_lng = row.get("lat_lng") or ""
    if isinstance(lat_lng, str) and "," in lat_lng:
        a, _, b = lat_lng.partition(",")
        try:
            lat, lng = float(a), float(b)
        except ValueError:
            lat, lng = None, None
    name = (row.get("location_name") or row.get("organisation_name") or "").strip() or "Food bank"
    lsoa = row.get("lsoa")
    return {
        "lat": lat,
        "lng": lng,
        "postcode": row.get("postcode"),
        "lsoa": lsoa if isinstance(lsoa, str) and lsoa else None,
        "name": name,
        "org": row.get("organisation_name"),
    }


class GiveFoodClient:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client
        self._owns_client = http_client is None

    async def fetch_foodbanks(self) -> list[dict[str, Any]]:
        """Fetch + trim the full food-bank dump. Raises on failure."""
        client = self._client or httpx.AsyncClient(timeout=60.0)
        try:
            response = await client.get(
                DUMP_URL, headers=GIVEFOOD_HEADERS, follow_redirects=True
            )
            response.raise_for_status()
            data: Any = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise GiveFoodUnavailableError(f"Give Food dump fetch failed: {exc!r}") from exc
        finally:
            if self._owns_client:
                await client.aclose()

        if not isinstance(data, list):
            raise GiveFoodUnavailableError("Give Food dump was not a JSON list")
        return [_trim(row) for row in data if isinstance(row, dict)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_givefood_client.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + commit**

```bash
cd server && uv run ruff format soundings/adapters/givefood/ tests/test_givefood_client.py && uv run ruff check soundings/adapters/givefood/
cd .. && git add server/soundings/adapters/givefood/__init__.py server/soundings/adapters/givefood/client.py server/tests/test_givefood_client.py
git commit -m "feat(givefood): client fetching + trimming the food-bank dump"
```

---

### Task 2: GiveFoodAdapter — counts via point-in-polygon

**Files:**
- Create: `server/soundings/adapters/givefood/adapter.py`
- Test: `server/tests/test_givefood_adapter.py`

**Interfaces:**
- Consumes: `GiveFoodClient.fetch_foodbanks()` (Task 1); `PassthroughAdapter` base (`self._cache`, `self._ttl`, `self._build_source_ref`, `self._engine`); `IndicatorValue` contract.
- Produces: `GiveFoodAdapter(engine, *, ttl=timedelta(hours=24), client=None, http_client=None)` with `source_id = "givefood"`; module constants `SOURCE_ID`, `FOOD_BANKS_INDICATOR = "infrastructure.food_banks_count"`, `METHODOLOGY_CAVEAT`; methods `_cached_dump() -> list[dict]`, `_locations_within(place_id) -> list[dict]`, `fetch_indicator(...)`.

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_givefood_adapter.py`:

```python
"""Integration tests for GiveFoodAdapter (fake client + real PostGIS test DB)."""

import pytest
from sqlalchemy import text

from soundings.adapters.givefood.adapter import (
    FOOD_BANKS_INDICATOR,
    GiveFoodAdapter,
)
from soundings.adapters.givefood.client import GiveFoodUnavailableError
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_place() -> None:
    """One LTLA polygon: the unit square (0,0)-(1,1)."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM cache.source_cache"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name, geom) VALUES "
                "('ltla24:FB1','ltla24','FB1','Foodland', "
                "ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((0 0,0 1,1 1,1 0,0 0)))'))"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO catalogue.source (id, label, publisher, publisher_url, "
                "dataset_url, licence, mode, rate_limit) VALUES "
                "('givefood','Give Food','Give Food','https://www.givefood.org.uk/', "
                "'https://www.givefood.org.uk/api/2/docs/','attribution','passthrough','{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )


class _FakeClient:
    """Stub returning canned trimmed dump rows."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.calls = 0

    async def fetch_foodbanks(self) -> list[dict]:
        self.calls += 1
        return self._rows


class _FailingClient:
    async def fetch_foodbanks(self) -> list[dict]:
        raise GiveFoodUnavailableError("boom")


# Two inside the unit square, one outside (lng=5).
_ROWS = [
    {"lat": 0.5, "lng": 0.5, "postcode": "A", "lsoa": "E01000001", "name": "Inside One", "org": "Org"},
    {"lat": 0.2, "lng": 0.8, "postcode": "B", "lsoa": "E01000002", "name": "Inside Two", "org": "Org"},
    {"lat": 0.5, "lng": 5.0, "postcode": "C", "lsoa": "E01000003", "name": "Outside", "org": "Org"},
]


async def test_fetch_indicator_counts_in_boundary_only() -> None:
    await _seed_place()
    fake = _FakeClient(_ROWS)
    adapter = GiveFoodAdapter(get_engine(), client=fake)
    iv = await adapter.fetch_indicator(FOOD_BANKS_INDICATOR, "ltla24:FB1", None)
    assert iv is not None
    assert iv.value == 2.0  # the outside one is excluded
    assert iv.unit == "count"
    assert iv.source.source_id == "givefood"


async def test_fetch_indicator_unknown_indicator_returns_none() -> None:
    await _seed_place()
    adapter = GiveFoodAdapter(get_engine(), client=_FakeClient(_ROWS))
    assert await adapter.fetch_indicator("not.food_banks", "ltla24:FB1", None) is None


async def test_fetch_indicator_second_call_uses_cache() -> None:
    await _seed_place()
    fake = _FakeClient(_ROWS)
    adapter = GiveFoodAdapter(get_engine(), client=fake)
    await adapter.fetch_indicator(FOOD_BANKS_INDICATOR, "ltla24:FB1", None)
    await adapter.fetch_indicator(FOOD_BANKS_INDICATOR, "ltla24:FB1", None)
    assert fake.calls == 1  # dump fetched once; count served from cache


async def test_fetch_indicator_transport_failure_propagates_uncached() -> None:
    await _seed_place()
    adapter = GiveFoodAdapter(get_engine(), client=_FailingClient())
    with pytest.raises(GiveFoodUnavailableError):
        await adapter.fetch_indicator(FOOD_BANKS_INDICATOR, "ltla24:FB1", None)
    # second call still raises -> nothing cached
    with pytest.raises(GiveFoodUnavailableError):
        await adapter.fetch_indicator(FOOD_BANKS_INDICATOR, "ltla24:FB1", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_givefood_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: soundings.adapters.givefood.adapter`.

- [ ] **Step 3: Implement the adapter (dump cache, matching, counts)**

Create `server/soundings/adapters/givefood/adapter.py`:

```python
"""GiveFoodAdapter — food-bank counts and locations from Give Food.

Fetches Give Food's daily food-bank dump once (cached 24h), then matches each
location to a place by point-in-polygon on its coordinates. The LSOA GSS code
on each row is a fallback when coordinates are missing.

Food banks are volunteered/maintained data; every returned value carries the
methodology caveat below.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from soundings.adapters.givefood.client import GiveFoodClient
from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.contracts.indicator_value import IndicatorValue

SOURCE_ID = "givefood"
FOOD_BANKS_INDICATOR = "infrastructure.food_banks_count"
METHODOLOGY_CAVEAT = (
    "Food bank locations from Give Food (givefood.org.uk), updated daily. "
    "Counts distribution locations whose coordinates fall within the place boundary."
)

_log = logging.getLogger(__name__)


class GiveFoodAdapter(PassthroughAdapter):
    source_id = SOURCE_ID

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        ttl: timedelta = timedelta(hours=24),
        client: GiveFoodClient | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(engine, ttl=ttl, rate_per_second=1.0, http_client=http_client)
        self._gf = client or GiveFoodClient(http_client=http_client)

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any | None:
        del client, cache_key
        raise NotImplementedError("GiveFoodAdapter routes via fetch_indicator override")

    async def _cached_dump(self) -> list[dict[str, Any]]:
        cached = await self._cache.get(self.source_id, "foodbanks:all")
        if isinstance(cached, list):
            return cached
        rows = await self._gf.fetch_foodbanks()
        await self._cache.put(self.source_id, "foodbanks:all", rows, ttl=self._ttl)
        return rows

    async def _locations_within(self, place_id: str) -> list[dict[str, Any]]:
        """Dump rows whose coordinates fall inside the place polygon.

        Coordinate-bearing rows are matched by ST_Within; rows lacking
        coordinates but carrying an LSOA code fall back to a place_hierarchy
        membership check.
        """
        rows = await self._cached_dump()
        coord_rows = [r for r in rows if r["lat"] is not None and r["lng"] is not None]
        nocoord_rows = [
            r for r in rows if (r["lat"] is None or r["lng"] is None) and r.get("lsoa")
        ]
        matched: list[dict[str, Any]] = []

        if coord_rows:
            lngs = [r["lng"] for r in coord_rows]
            lats = [r["lat"] for r in coord_rows]
            async with self._engine.connect() as conn:
                res = (
                    await conn.execute(
                        text(
                            """
                            SELECT u.idx
                            FROM unnest(:lngs ::float8[], :lats ::float8[])
                                WITH ORDINALITY AS u(lng, lat, idx)
                            JOIN geography.place g ON g.id = :pid
                            WHERE g.geom IS NOT NULL
                              AND ST_Within(ST_SetSRID(ST_Point(u.lng, u.lat), 4326), g.geom)
                            """
                        ),
                        {"lngs": lngs, "lats": lats, "pid": place_id},
                    )
                ).all()
            matched.extend(coord_rows[r.idx - 1] for r in res)

        if nocoord_rows:
            lsoa_ids = ["lsoa21:" + r["lsoa"] for r in nocoord_rows]
            async with self._engine.connect() as conn:
                res = (
                    await conn.execute(
                        text(
                            """
                            SELECT h.child_id AS id FROM geography.place_hierarchy h
                            WHERE h.parent_id = :pid AND h.child_id = ANY(:ids)
                            UNION
                            SELECT g.id AS id FROM geography.place g
                            WHERE g.id = :pid AND g.id = ANY(:ids)
                            """
                        ),
                        {"pid": place_id, "ids": lsoa_ids},
                    )
                ).all()
            within = {r.id for r in res}
            matched.extend(r for r in nocoord_rows if "lsoa21:" + r["lsoa"] in within)

        return matched

    async def fetch_indicator(
        self, indicator_key: str, place_id: str, period: str | None
    ) -> IndicatorValue | None:
        if indicator_key != FOOD_BANKS_INDICATOR:
            return None

        cache_key = f"count:{place_id}"
        cached = await self._cache.get(self.source_id, cache_key)
        if isinstance(cached, dict):
            count = int(cached.get("count", 0))
            period_used = str(cached.get("period", ""))
        else:
            within = await self._locations_within(place_id)
            count = len(within)
            period_used = period or datetime.now(tz=UTC).strftime("%Y-%m")
            await self._cache.put(
                self.source_id,
                cache_key,
                {"count": count, "period": period_used},
                ttl=self._ttl,
            )

        source_ref = await self._build_source_ref(
            retrieved_at=datetime.now(tz=UTC), cache_status="cached"
        )
        return IndicatorValue(
            place_id=place_id,
            indicator=indicator_key,
            value=float(count),
            unit="count",
            period=period_used,
            source=source_ref,
            caveats=[METHODOLOGY_CAVEAT],
            confidence="official",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_givefood_adapter.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + commit**

```bash
cd server && uv run ruff format soundings/adapters/givefood/adapter.py tests/test_givefood_adapter.py && uv run ruff check soundings/adapters/givefood/adapter.py
cd .. && git add server/soundings/adapters/givefood/adapter.py server/tests/test_givefood_adapter.py
git commit -m "feat(givefood): food-bank counts via point-in-polygon"
```

---

### Task 3: GiveFoodAdapter — map points + pre-warming

**Files:**
- Modify: `server/soundings/adapters/givefood/adapter.py`
- Test: `server/tests/test_givefood_adapter.py`

**Interfaces:**
- Consumes: `_locations_within` + `_cached_dump` (Task 2).
- Produces: `amenity_locations(indicator_key, place_id) -> dict | None` (GeoJSON FeatureCollection; `None` for non-food-bank keys); `pre_warm_for_places(place_ids: list[str]) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_givefood_adapter.py`:

```python
async def test_amenity_locations_returns_points_in_boundary() -> None:
    await _seed_place()
    adapter = GiveFoodAdapter(get_engine(), client=_FakeClient(_ROWS))
    fc = await adapter.amenity_locations(FOOD_BANKS_INDICATOR, "ltla24:FB1")
    assert fc is not None and fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2  # outside one excluded
    f0 = fc["features"][0]
    assert f0["geometry"]["type"] == "Point"
    # [lng, lat] order; properties carry name + layer
    assert f0["geometry"]["coordinates"] == [0.5, 0.5]
    assert f0["properties"]["layer"] == FOOD_BANKS_INDICATOR
    assert f0["properties"]["name"] in {"Inside One", "Inside Two"}


async def test_amenity_locations_unknown_indicator_returns_none() -> None:
    await _seed_place()
    adapter = GiveFoodAdapter(get_engine(), client=_FakeClient(_ROWS))
    assert await adapter.amenity_locations("not.food_banks", "ltla24:FB1") is None


async def test_pre_warm_caches_counts_for_places() -> None:
    await _seed_place()
    fake = _FakeClient(_ROWS)
    adapter = GiveFoodAdapter(get_engine(), client=fake)
    await adapter.pre_warm_for_places(["ltla24:FB1"])
    # After warming, a fetch makes no further upstream call.
    fake.calls = 0
    iv = await adapter.fetch_indicator(FOOD_BANKS_INDICATOR, "ltla24:FB1", None)
    assert iv is not None and iv.value == 2.0
    assert fake.calls == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_givefood_adapter.py -k "amenity_locations or pre_warm" -v`
Expected: FAIL — `AttributeError: 'GiveFoodAdapter' object has no attribute 'amenity_locations'`.

- [ ] **Step 3: Implement points + pre-warm**

In `adapter.py`, add these methods after `fetch_indicator`:

```python
    async def amenity_locations(self, indicator_key: str, place_id: str) -> dict | None:
        """GeoJSON FeatureCollection of food-bank locations within a place."""
        if indicator_key != FOOD_BANKS_INDICATOR:
            return None

        cache_key = f"geo:{place_id}"
        cached = await self._cache.get(self.source_id, cache_key)
        if isinstance(cached, dict):
            return cached

        within = await self._locations_within(place_id)
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lng"], r["lat"]]},
                "properties": {"name": r["name"], "layer": indicator_key},
            }
            for r in within
            if r["lat"] is not None and r["lng"] is not None
        ]
        fc = {"type": "FeatureCollection", "features": features}
        await self._cache.put(self.source_id, cache_key, fc, ttl=self._ttl)
        return fc

    async def pre_warm_for_places(self, place_ids: list[str]) -> None:
        """Warm the dump once, then per-place counts. Driven by the pre_warmer
        daemon on the source's daily cadence so user reads stay warm."""
        await self._cached_dump()
        for place_id in place_ids:
            try:
                await self.fetch_indicator(FOOD_BANKS_INDICATOR, place_id, None)
            except Exception:
                _log.exception("givefood pre_warm failed for place_id=%s", place_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_givefood_adapter.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint + commit**

```bash
cd server && uv run ruff format soundings/adapters/givefood/adapter.py tests/test_givefood_adapter.py && uv run ruff check soundings/adapters/givefood/adapter.py
cd .. && git add server/soundings/adapters/givefood/adapter.py server/tests/test_givefood_adapter.py
git commit -m "feat(givefood): food-bank map points and pre-warming"
```

---

### Task 4: Wire into catalogue + register + retire OSM food banks

**Files:**
- Modify: `catalogue/sources.yaml`
- Modify: `catalogue/indicators.yaml`
- Modify: `server/soundings/app.py`
- Modify: `server/soundings/adapters/osm_overpass/adapter.py`
- Modify: `server/tests/test_osm_overpass_adapter.py`
- Test: `server/tests/test_catalogue_loader.py`

**Interfaces:**
- Consumes: `GiveFoodAdapter` (Tasks 2-3); the catalogue loader `load_catalogue_into_db`.
- Produces: a registered `givefood` source whose adapter serves `infrastructure.food_banks_count`; OSM no longer serves that indicator.

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_catalogue_loader.py` (imports `load_catalogue_into_db`, `SOURCES_YAML`, `INDICATORS_YAML`, `get_engine`, `text` already per its header):

```python
async def test_food_banks_indicator_sourced_from_givefood() -> None:
    engine = get_engine()
    await load_catalogue_into_db(engine, sources_path=SOURCES_YAML, indicators_path=INDICATORS_YAML)
    async with engine.connect() as conn:
        source_id = (
            await conn.execute(
                text("SELECT source_id FROM catalogue.indicator WHERE key = :k"),
                {"k": "infrastructure.food_banks_count"},
            )
        ).scalar_one()
        givefood = (
            await conn.execute(
                text("SELECT count(*) FROM catalogue.source WHERE id = 'givefood'")
            )
        ).scalar_one()
    assert source_id == "givefood"
    assert givefood == 1
```

Also add to `server/tests/test_osm_overpass_adapter.py` a test that OSM no longer serves food banks:

```python
async def test_osm_no_longer_serves_food_banks() -> None:
    await _seed_place()
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=_FakeOverpassClient({}))
    assert (
        await adapter.fetch_indicator("infrastructure.food_banks_count", "ltla24:E06000004", None)
    ) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_catalogue_loader.py::test_food_banks_indicator_sourced_from_givefood tests/test_osm_overpass_adapter.py::test_osm_no_longer_serves_food_banks -v`
Expected: FAIL — source_id is still `osm_overpass`; OSM still returns a value for food banks.

- [ ] **Step 3a: Add the Give Food source** — in `catalogue/sources.yaml`, after the `osm_overpass` entry add:

```yaml
  - id: givefood
    label: Give Food
    publisher: Give Food
    publisher_url: https://www.givefood.org.uk/
    dataset_url: https://www.givefood.org.uk/api/2/docs/
    licence: "Give Food terms - attribution required"
    mode: passthrough
    ttl_hours: 24
    # Daily warm pass — the dump updates daily; the pre_warmer warms the dump
    # and per-LTLA counts so user reads stay warm.
    refresh_cadence: "0 4 * * *"
    rate_limit: { rps: 1 }
```

- [ ] **Step 3b: Re-point the indicator** — in `catalogue/indicators.yaml`, replace the `infrastructure.food_banks_count` block with:

```yaml
  - key: infrastructure.food_banks_count
    label: "Food banks"
    description: "Count of food bank distribution locations within the place boundary, from Give Food (givefood.org.uk)."
    unit: "count"
    higher_is: null
    source_id: "givefood"
    available_at: ["ltla24", "utla24"]
    refresh_cadence: "daily"
    caveats:
      - "Food bank locations from Give Food, updated daily. Counts distribution locations whose coordinates fall within the place boundary."
```

- [ ] **Step 3c: Register the adapter** — in `server/soundings/app.py`, add the import near the other adapter imports and the registration alongside the others (after the `osm_overpass` registration):

```python
from soundings.adapters.givefood.adapter import GiveFoodAdapter
```
```python
    registry.register("givefood", GiveFoodAdapter)
```

- [ ] **Step 3d: Retire OSM food banks** — in `server/soundings/adapters/osm_overpass/adapter.py`, delete the `infrastructure.food_banks_count` entry from `INDICATOR_TAGS`:

```python
    "infrastructure.food_banks_count": [
        {"amenity": "food_bank"},
        {"social_facility": "food_bank"},
    ],
```
(remove those four lines entirely).

- [ ] **Step 3e: Fix the OSM test that used food banks** — in `server/tests/test_osm_overpass_adapter.py`, the existing `test_amenity_locations_builds_feature_collection` builds points for `infrastructure.food_banks_count`. Re-point it to a still-present amenity. Change its body to use libraries:

```python
async def test_amenity_locations_builds_feature_collection() -> None:
    await _seed_place()
    fake = _FakeLocationsClient(
        {
            ("amenity", "library"): [{"lat": 54.77, "lng": -1.57, "name": "Durham Library"}],
        }
    )
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=fake)
    fc = await adapter.amenity_locations("infrastructure.libraries_count", "ltla24:E06000004")

    assert fc is not None and fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    f0 = fc["features"][0]
    assert f0["geometry"]["coordinates"] == [-1.57, 54.77]
    assert f0["properties"]["layer"] == "infrastructure.libraries_count"
```

- [ ] **Step 4: Run tests to verify they pass (and nothing else broke)**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_catalogue_loader.py tests/test_osm_overpass_adapter.py -v`
Then the unit suite: `cd server && uv run pytest -m "not live and not integration" -q`
Expected: PASS. If another OSM test references `food_banks` in `INDICATOR_TAGS`, update it to drop that key (report any such change).

- [ ] **Step 5: Lint + commit**

```bash
cd server && uv run ruff format soundings/app.py soundings/adapters/osm_overpass/adapter.py tests/test_osm_overpass_adapter.py tests/test_catalogue_loader.py && uv run ruff check soundings/app.py soundings/adapters/osm_overpass/adapter.py
cd .. && git add catalogue/sources.yaml catalogue/indicators.yaml server/soundings/app.py server/soundings/adapters/osm_overpass/adapter.py server/tests/test_osm_overpass_adapter.py server/tests/test_catalogue_loader.py
git commit -m "feat(givefood): re-point food banks to Give Food, retire OSM tag"
```

---

### Task 5: Source-aware `/amenities/geometry` endpoint

**Files:**
- Modify: `server/soundings/http/place_geometry.py`
- Test: `server/tests/test_place_geometry.py`

**Interfaces:**
- Consumes: `request.app.state.adapter_registry.adapter_for_source(source_id)`; `request.app.state.engine`; `catalogue.indicator(key, source_id)`.
- Produces: `/amenities/geometry` that resolves each indicator's `source_id` from the catalogue and calls that adapter's `amenity_locations`, merging the results.

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_place_geometry.py` (it already has `_StubRegistry`/`_StubOsmAdapter` from the map feature — extend with a source-aware stub):

```python
class _SourceAwareRegistry:
    def __init__(self, by_source: dict[str, object]) -> None:
        self._by_source = by_source

    def adapter_for_source(self, source_id: str):
        return self._by_source[source_id]


class _LayerStubAdapter:
    """Tags each returned feature with WHICH adapter (source) produced it, so
    the test can prove routing — not just that a layer name survived."""

    def __init__(self, source_tag: str) -> None:
        self._source_tag = source_tag

    async def amenity_locations(self, indicator_key: str, place_id: str) -> dict:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-1.5, 54.7]},
                    "properties": {
                        "name": indicator_key,
                        "layer": indicator_key,
                        "source": self._source_tag,
                    },
                }
            ],
        }


async def test_amenities_geometry_routes_by_indicator_source(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = get_engine()
    # Seed two indicators with different sources in the catalogue.
    async with engine.begin() as conn:
        for sid in ("givefood", "osm_overpass"):
            await conn.execute(
                text(
                    "INSERT INTO catalogue.source (id, label, publisher, licence, mode, rate_limit) "
                    "VALUES (:s, :s, 'p', 'x', 'passthrough', '{}'::jsonb) ON CONFLICT (id) DO NOTHING"
                ),
                {"s": sid},
            )
        await conn.execute(
            text(
                "INSERT INTO catalogue.indicator (key, label, unit, source_id, available_at, caveats, related_keys) "
                "VALUES ('infrastructure.food_banks_count','fb','count','givefood', ARRAY['ltla24'], '[]'::jsonb, ARRAY[]::varchar[]) "
                "ON CONFLICT (key) DO UPDATE SET source_id='givefood'"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO catalogue.indicator (key, label, unit, source_id, available_at, caveats, related_keys) "
                "VALUES ('infrastructure.schools_count','sc','count','osm_overpass', ARRAY['ltla24'], '[]'::jsonb, ARRAY[]::varchar[]) "
                "ON CONFLICT (key) DO UPDATE SET source_id='osm_overpass'"
            )
        )

    gf_adapter = _LayerStubAdapter("givefood")
    osm_adapter = _LayerStubAdapter("osm_overpass")
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        monkeypatch.setattr(
            app.state,
            "adapter_registry",
            _SourceAwareRegistry({"givefood": gf_adapter, "osm_overpass": osm_adapter}),
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/v1/place/ltla24:E06000047/amenities/geometry",
                params={"indicators": "infrastructure.food_banks_count,infrastructure.schools_count"},
            )
    assert resp.status_code == 200
    # Each indicator must be served by the adapter that OWNS it (its source).
    source_by_layer = {
        f["properties"]["layer"]: f["properties"]["source"] for f in resp.json()["features"]
    }
    assert source_by_layer == {
        "infrastructure.food_banks_count": "givefood",
        "infrastructure.schools_count": "osm_overpass",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_place_geometry.py -k routes_by_indicator_source -v`
Expected: FAIL — the current endpoint hardcodes `adapter_for_source("osm_overpass")` and uses that one adapter for every key, so the food-bank feature comes back tagged `source: "osm_overpass"` instead of `"givefood"`, and the `source_by_layer` assertion fails (`food_banks_count` maps to `osm_overpass`, not `givefood`).

- [ ] **Step 3: Make the endpoint source-aware**

In `server/soundings/http/place_geometry.py`, replace the body of `get_amenities_geometry` with:

```python
@router.get("/place/{place_id}/amenities/geometry")
async def get_amenities_geometry(
    request: Request,
    place_id: str,
    indicators: str = Query(..., description="comma-separated indicator keys"),
) -> dict[str, object]:
    """Merged FeatureCollection of amenity point locations. Each indicator is
    routed to the adapter that owns it (per its catalogue source_id), so food
    banks come from Give Food while schools/GPs come from OSM. Per-indicator
    failures degrade to a partial collection rather than failing the request."""
    keys = [k.strip() for k in indicators.split(",") if k.strip()][:6]
    engine = request.app.state.engine
    registry = request.app.state.adapter_registry

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT key, source_id FROM catalogue.indicator WHERE key = ANY(:keys)"),
                {"keys": keys},
            )
        ).all()
    source_by_key = {r.key: r.source_id for r in rows}

    features: list[dict[str, object]] = []
    errors: list[str] = []
    for key in keys:
        source_id = source_by_key.get(key)
        if source_id is None:
            errors.append(f"{key}: unknown indicator")
            continue
        try:
            adapter = registry.adapter_for_source(source_id)
            fc = await adapter.amenity_locations(key, place_id)
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            errors.append(f"{key}: {exc.__class__.__name__}")
            continue
        if fc:
            features.extend(fc.get("features", []))

    result: dict[str, object] = {"type": "FeatureCollection", "features": features}
    if errors:
        result["errors"] = errors
    return result
```

(If the file still imports anything now unused from the old hardcoded version, leave imports as-is unless ruff flags them.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_place_geometry.py -v`
Expected: PASS (existing amenities/children/peers tests + the new routing test).

- [ ] **Step 5: Lint + commit**

```bash
cd server && uv run ruff format soundings/http/place_geometry.py tests/test_place_geometry.py && uv run ruff check soundings/http/place_geometry.py
cd .. && git add server/soundings/http/place_geometry.py server/tests/test_place_geometry.py
git commit -m "feat(api): route amenity geometry by each indicator's source"
```

---

### Task 6: End-to-end smoke test

**Files:** none (verification + a docs note only).

**Interfaces:** Consumes the whole feature.

- [ ] **Step 1: Rebuild and bring up the stack**

```bash
cd /Users/tomcwxyz/code/dataforaction-tom/soundings
docker compose -f infra/docker-compose.yml --project-directory . build server 2>&1 | tail -3
docker compose -f infra/docker-compose.yml --project-directory . up -d server 2>&1 | tail -3
for i in $(seq 1 20); do curl -fsS http://127.0.0.1:8001/healthz >/dev/null 2>&1 && break; sleep 2; done
```

- [ ] **Step 2: Verify the count path (orchestrator → Give Food)**

```bash
curl -s -X POST http://127.0.0.1:8001/v1/tools/get_indicators \
  -H 'Content-Type: application/json' \
  -d '{"place_id":"ltla24:E06000047","indicators":["infrastructure.food_banks_count"]}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);r=d['results'][0];print('food banks:',r['value'],'source:',r['source']['source_id'])"
```
Expected: a count in the tens (~41 for County Durham), `source: givefood`. (First call fetches the 12 MB dump — allow a few seconds.)

- [ ] **Step 3: Verify the map points path (source-aware endpoint)**

```bash
curl -s "http://127.0.0.1:8001/v1/place/ltla24:E06000047/amenities/geometry?indicators=infrastructure.food_banks_count" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('food bank points:',len(d['features']),'errors:',d.get('errors'))"
```
Expected: points in the tens, `errors: None`.

- [ ] **Step 4: Record the result**

Note the observed counts in the commit body. If Give Food is unreachable from the container (network), the value will be a caveat/empty and the endpoints return an `errors` entry — record that instead and flag it, do not treat a network failure as a code defect.

- [ ] **Step 5: Commit the smoke result**

```bash
cd /Users/tomcwxyz/code/dataforaction-tom/soundings
git commit --allow-empty -m "test(givefood): end-to-end smoke (County Durham food banks)"
```

---

## Self-Review notes (addressed)

- **Spec coverage:** client (T1), counts + matching (T2), points + pre-warm (T3), source/indicator/registration/OSM-retirement (T4), source-aware endpoint (T5), e2e smoke (T6). Attribution (source row in T4), error-not-cached discipline (T1/T2 tests), point-in-polygon + LSOA fallback (T2) all covered.
- **Type consistency:** the trimmed record shape (`lat/lng/postcode/lsoa/name/org`) is defined in T1 and consumed verbatim in T2/T3; `FOOD_BANKS_INDICATOR` constant is shared; `amenity_locations` returns the same FeatureCollection shape the map renderer and `/amenities/geometry` already consume; `_locations_within` is defined in T2 and reused in T3.
- **Deferred (per spec):** "needs" data, org-level aggregation, the `/api/2/locations/` endpoint.
- **Watch:** removing `food_banks` from OSM `INDICATOR_TAGS` (T4) breaks any OSM test that references it — T4 Step 3e fixes the known one (`test_amenity_locations_builds_feature_collection`); Step 4 re-runs the suite to catch others.

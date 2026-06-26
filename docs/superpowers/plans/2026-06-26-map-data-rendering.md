# Map Data Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Ask `map` block render data — OSM amenity point locations and indicator choropleths (sub-area or peer) — not just a place boundary.

**Architecture:** Two new browser-called HTTP endpoints serve GeoJSON (amenity points from OSM `out center`, and LSOA-children polygons carrying an indicator value). The MapLibre renderer gains a points map and a fixed choropleth colour scale. The `map` block schema gains fields (`granularity`, `overlay.indicator_keys`) that let the model pick the mode; the prompt teaches it when to use each.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy(async) / PostGIS / pydantic; Astro 4 / TypeScript / MapLibre GL / Observable Plot; pytest (`integration` marker needs the Docker Postgres on `localhost:5433`); vitest (happy-dom).

## Global Constraints

- Conventional Commits (`feat`, `fix`, `test`, `docs`, `chore`); subject ≤72 chars; never include Claude/AI attribution.
- TDD: failing test → minimal code → green → commit. One feature branch (`feat/slice-1-chart-renderers`, already checked out); do not commit to `main`.
- Never `--no-verify`; pre-commit runs ruff + ruff-format (Python) — pre-format changed files.
- Python integration tests MUST run against the test DB, never the dev DB. Prefix every integration run with:
  `DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test"`
- Python unit tests (no DB): `cd server && uv run pytest -m "not live and not integration" …`
- UI tests: `cd ui && npx vitest run …`
- OSM transport rules already in `client.py`: send `OVERPASS_HEADERS`, try `OVERPASS_PRIMARY` then `OVERPASS_FALLBACK`, raise `OverpassUnavailableError` on total failure, never cache a fabricated result.
- v1 does NOT combine choropleth + points in one block (points take precedence), does NOT implement `air_quality`/`organisations` overlays, does NOT pre-warm amenity locations.

---

### Task 1: OSM client — `locations_by_tag`

**Files:**
- Modify: `server/soundings/adapters/osm_overpass/client.py`
- Test: `server/tests/test_osm_overpass_client.py`

**Interfaces:**
- Consumes: existing module constants `OVERPASS_PRIMARY`, `OVERPASS_FALLBACK`, `OVERPASS_HEADERS`, `OverpassUnavailableError`, and the `self._limiter` / `self._client` / `self._owns_client` instance state.
- Produces: `OsmOverpassClient.locations_by_tag(self, tag_key: str, tag_value: str, bbox: tuple[float, float, float, float], *, max_results: int = 1000) -> list[dict[str, Any]]` — each dict `{"lat": float, "lng": float, "name": str | None}`. Module helper `_extract_locations(payload: Any, max_results: int) -> list[dict[str, Any]]`.

- [ ] **Step 1: Write the failing tests**

Add to `server/tests/test_osm_overpass_client.py`:

```python
def _locations_payload() -> dict[str, object]:
    # A node (direct lat/lon), a way (center), and one unnamed node.
    return {
        "version": 0.6,
        "elements": [
            {"type": "node", "id": 1, "lat": 54.77, "lon": -1.57, "tags": {"name": "Durham Foodbank"}},
            {"type": "way", "id": 2, "center": {"lat": 54.70, "lon": -1.50}, "tags": {"name": "St X Pantry"}},
            {"type": "node", "id": 3, "lat": 54.60, "lon": -1.40, "tags": {}},
        ],
    }


async def test_locations_by_tag_parses_nodes_and_centers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=_locations_payload())

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        pts = await client.locations_by_tag("amenity", "food_bank", (54.5, -1.7, 54.9, -1.3))

    assert len(pts) == 3
    assert pts[0] == {"lat": 54.77, "lng": -1.57, "name": "Durham Foodbank"}
    assert pts[1]["lat"] == 54.70 and pts[1]["lng"] == -1.50  # way centroid
    assert pts[2]["name"] is None  # unnamed


async def test_locations_by_tag_empty_elements_returns_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"version": 0.6, "elements": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        pts = await client.locations_by_tag("amenity", "school", (54.5, -1.7, 54.9, -1.3))
    assert pts == []  # valid "none here", not an error


async def test_locations_by_tag_raises_when_all_endpoints_fail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503, text="overloaded")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = OsmOverpassClient(http_client=http)
        with pytest.raises(OverpassUnavailableError):
            await client.locations_by_tag("amenity", "school", (54.5, -1.7, 54.9, -1.3))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_osm_overpass_client.py -k locations -v`
Expected: FAIL — `AttributeError: 'OsmOverpassClient' object has no attribute 'locations_by_tag'`.

- [ ] **Step 3: Implement the client method + helpers**

In `client.py`, add the public method (place it after `count_by_tag`):

```python
    async def locations_by_tag(
        self,
        tag_key: str,
        tag_value: str,
        bbox: tuple[float, float, float, float],
        *,
        max_results: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch element coordinates (not just a count) for a tag in a bbox.

        Emits `out center tags` so ways/relations carry a centroid. An empty
        result is a valid 'none here' ([]); only transport/parse failure on
        every endpoint raises OverpassUnavailableError.
        """
        south, west, north, east = bbox
        bbox_str = f"{south},{west},{north},{east}"
        query = (
            f"[out:json][timeout:25];\n"
            f"(\n"
            f'  node["{tag_key}"="{tag_value}"]({bbox_str});\n'
            f'  way["{tag_key}"="{tag_value}"]({bbox_str});\n'
            f'  relation["{tag_key}"="{tag_value}"]({bbox_str});\n'
            f");\n"
            f"out center tags {max_results};\n"
        )
        payload = await self._post_payload(query)
        return _extract_locations(payload, max_results)

    async def _post_payload(self, query: str) -> Any:
        """POST a query, returning parsed JSON from the first endpoint that
        responds. Raises OverpassUnavailableError if all endpoints fail."""
        last_error: Exception | None = None
        for endpoint in (OVERPASS_PRIMARY, OVERPASS_FALLBACK):
            try:
                return await self._fetch_json(endpoint, query)
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_error = exc
                continue
        raise OverpassUnavailableError(
            f"all Overpass endpoints failed; last error: {last_error!r}"
        )

    async def _fetch_json(self, endpoint: str, query: str) -> Any:
        """POST to one endpoint and return parsed JSON (raises on HTTP/JSON error)."""
        async with self._limiter:
            client = self._client or httpx.AsyncClient(timeout=60.0)
            try:
                response = await client.post(
                    endpoint, data={"data": query}, headers=OVERPASS_HEADERS
                )
                response.raise_for_status()
                payload: Any = response.json()
            finally:
                if self._owns_client:
                    await client.aclose()
        return payload
```

At module level (next to `_extract_total`), add:

```python
def _extract_locations(payload: Any, max_results: int) -> list[dict[str, Any]]:
    """Pull {lat, lng, name} points from an Overpass 'out center' response."""
    out: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return out
    elements = payload.get("elements")
    if not isinstance(elements, list):
        return out
    for el in elements:
        if not isinstance(el, dict) or el.get("type") == "count":
            continue
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            center = el.get("center")
            if isinstance(center, dict):
                lat = center.get("lat")
                lon = center.get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags") if isinstance(el.get("tags"), dict) else {}
        name = tags.get("name")
        out.append(
            {"lat": float(lat), "lng": float(lon), "name": name if isinstance(name, str) else None}
        )
        if len(out) >= max_results:
            break
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_osm_overpass_client.py -v`
Expected: PASS (all existing + 3 new).

- [ ] **Step 5: Lint + commit**

```bash
cd server && uv run ruff format soundings/adapters/osm_overpass/client.py tests/test_osm_overpass_client.py && uv run ruff check soundings/adapters/osm_overpass/client.py
cd .. && git add server/soundings/adapters/osm_overpass/client.py server/tests/test_osm_overpass_client.py
git commit -m "feat(osm): fetch amenity locations via Overpass out center"
```

---

### Task 2: OSM adapter — `amenity_locations`

**Files:**
- Modify: `server/soundings/adapters/osm_overpass/adapter.py`
- Test: `server/tests/test_osm_overpass_adapter.py`

**Interfaces:**
- Consumes: `INDICATOR_TAGS` (module constant), instance helpers `self._get_bbox`, `self._cache` (`.get`/`.put`), `self._ttl`, and the Overpass client `self._overpass.locations_by_tag(...)` from Task 1.
- Produces: `OsmOverpassAdapter.amenity_locations(self, indicator_key: str, place_id: str) -> dict | None` — a GeoJSON FeatureCollection dict (or `None` for a non-amenity indicator). Each feature: `{"type": "Feature", "geometry": {"type": "Point", "coordinates": [lng, lat]}, "properties": {"name": str | None, "layer": indicator_key}}`.

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_osm_overpass_adapter.py`. The existing `_FakeOverpassClient` only stubs `count_by_tag`; extend the test with a locations-aware fake (define it inside the test module, after `_FakeOverpassClient`):

```python
class _FakeLocationsClient(OsmOverpassClient):
    """Stub returning canned point lists per tag query."""

    def __init__(self, points: dict[tuple[str, str], list[dict[str, object]]]) -> None:
        self._points = points
        self.calls: list[tuple[str, str]] = []

    async def locations_by_tag(self, tag_key, tag_value, bbox, *, max_results=1000):  # type: ignore[override]
        self.calls.append((tag_key, tag_value))
        return self._points.get((tag_key, tag_value), [])


async def test_amenity_locations_builds_feature_collection() -> None:
    await _seed_place()
    fake = _FakeLocationsClient(
        {
            ("amenity", "food_bank"): [{"lat": 54.77, "lng": -1.57, "name": "Durham Foodbank"}],
            ("social_facility", "food_bank"): [{"lat": 54.70, "lng": -1.50, "name": "Pantry"}],
        }
    )
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=fake)
    fc = await adapter.amenity_locations("infrastructure.food_banks_count", "ltla24:E06000004")

    assert fc is not None and fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 2
    f0 = fc["features"][0]
    assert f0["geometry"]["type"] == "Point"
    assert f0["geometry"]["coordinates"] == [-1.57, 54.77]  # [lng, lat]
    assert f0["properties"]["layer"] == "infrastructure.food_banks_count"


async def test_amenity_locations_unknown_indicator_returns_none() -> None:
    await _seed_place()
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=_FakeLocationsClient({}))
    assert await adapter.amenity_locations("not.an.amenity", "ltla24:E06000004") is None


async def test_amenity_locations_second_call_uses_cache() -> None:
    await _seed_place()
    fake = _FakeLocationsClient({("amenity", "school"): [{"lat": 54.7, "lng": -1.5, "name": "A"}]})
    adapter = OsmOverpassAdapter(get_engine(), overpass_client=fake)
    await adapter.amenity_locations("infrastructure.schools_count", "ltla24:E06000004")
    await adapter.amenity_locations("infrastructure.schools_count", "ltla24:E06000004")
    assert len(fake.calls) == 1  # second served from cache
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_osm_overpass_adapter.py -k amenity_locations -v`
Expected: FAIL — `AttributeError: 'OsmOverpassAdapter' object has no attribute 'amenity_locations'`.

- [ ] **Step 3: Implement `amenity_locations`**

In `adapter.py`, add the method after `fetch_indicator` (before `_get_bbox`):

```python
    async def amenity_locations(self, indicator_key: str, place_id: str) -> dict | None:
        """GeoJSON FeatureCollection of amenity point locations for one
        indicator within a place. Cached under `osmgeo:{key}:{place_id}`.

        Returns None for a non-amenity indicator; an empty FeatureCollection
        when the place has no geometry or no matching amenities. A transport
        failure propagates (not cached), like the count path.
        """
        tags = INDICATOR_TAGS.get(indicator_key)
        if tags is None:
            return None

        cache_key = f"osmgeo:{indicator_key}:{place_id}"
        cached = await self._cache.get(self.source_id, cache_key)
        if isinstance(cached, dict):
            return cached

        bbox = await self._get_bbox(place_id)
        if bbox is None:
            return {"type": "FeatureCollection", "features": []}

        seen: set[tuple[float, float]] = set()
        features: list[dict[str, Any]] = []
        for tag_dict in tags:
            for k, v in tag_dict.items():
                for pt in await self._overpass.locations_by_tag(k, v, bbox):
                    key = (round(pt["lat"], 6), round(pt["lng"], 6))
                    if key in seen:
                        continue
                    seen.add(key)
                    features.append(
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [pt["lng"], pt["lat"]]},
                            "properties": {"name": pt["name"], "layer": indicator_key},
                        }
                    )

        fc = {"type": "FeatureCollection", "features": features}
        await self._cache.put(self.source_id, cache_key, fc, ttl=self._ttl)
        return fc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_osm_overpass_adapter.py -v`
Expected: PASS (existing + 3 new).

- [ ] **Step 5: Lint + commit**

```bash
cd server && uv run ruff format soundings/adapters/osm_overpass/adapter.py tests/test_osm_overpass_adapter.py && uv run ruff check soundings/adapters/osm_overpass/adapter.py
cd .. && git add server/soundings/adapters/osm_overpass/adapter.py server/tests/test_osm_overpass_adapter.py
git commit -m "feat(osm): adapter method for amenity point GeoJSON (cached)"
```

---

### Task 3: Endpoint — `GET /place/{id}/children/geometry`

**Files:**
- Modify: `server/soundings/http/place_geometry.py`
- Test: `server/tests/test_place_geometry.py`

**Interfaces:**
- Consumes: `router` (APIRouter, prefix `/v1`), `_parse_geojson` helper, `request.app.state.engine`, the `geography.place_hierarchy` + `geography.place` + `data.indicator_value` tables.
- Produces: route `GET /v1/place/{place_id}/children/geometry?indicator=&period=&child_type=lsoa21` → FeatureCollection; each feature `properties = {id, name, value}`, only children that have a value for the indicator.

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_place_geometry.py`. Seed an LTLA with two LSOA children (one with an IMD value, one without):

```python
async def _seed_parent_with_lsoa_children() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name, geom) VALUES "
                "('ltla24:P1','ltla24','P1','Parent', ST_GeomFromEWKT(:g))"
            ),
            {"g": "SRID=4326;MULTIPOLYGON(((0 0,0 2,2 0,0 0)))"},
        )
        for cid, geom in [
            ("lsoa21:L1", "SRID=4326;MULTIPOLYGON(((0 0,0 1,1 0,0 0)))"),
            ("lsoa21:L2", "SRID=4326;MULTIPOLYGON(((1 1,1 2,2 1,1 1)))"),
        ]:
            await conn.execute(
                text(
                    "INSERT INTO geography.place (id, type, code, name, geom) VALUES "
                    "(:id,'lsoa21',:c,:n, ST_GeomFromEWKT(:g))"
                ),
                {"id": cid, "c": cid.split(":")[1], "n": cid, "g": geom},
            )
            await conn.execute(
                text("INSERT INTO geography.place_hierarchy (child_id, parent_id) VALUES (:c,'ltla24:P1')"),
                {"c": cid},
            )
        # Only L1 has an IMD value.
        await conn.execute(
            text(
                "INSERT INTO data.indicator_value (place_id, indicator_key, value, unit, period, source_id) "
                "VALUES ('lsoa21:L1','deprivation.imd.score', 42.0, 'score', '2025', 'mhclg.imd2025')"
            )
        )


async def test_children_geometry_returns_valued_children_only() -> None:
    await _seed_parent_with_lsoa_children()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/place/ltla24:P1/children/geometry",
            params={"indicator": "deprivation.imd.score"},
        )
    assert resp.status_code == 200
    fc = resp.json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1  # L2 has no value → excluded
    props = fc["features"][0]["properties"]
    assert props["id"] == "lsoa21:L1" and props["value"] == 42.0


async def test_children_geometry_empty_for_indicator_without_subarea_data() -> None:
    await _seed_parent_with_lsoa_children()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/place/ltla24:P1/children/geometry",
            params={"indicator": "population.total"},
        )
    assert resp.status_code == 200
    assert resp.json()["features"] == []
```

Confirm the test file already imports `app`, `ASGITransport`, `AsyncClient`, `text` (it does per its header).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_place_geometry.py -k children -v`
Expected: FAIL — 404 (route not found).

- [ ] **Step 3: Implement the route**

In `place_geometry.py`, add `Query` to the existing FastAPI import if missing (it already imports `Query`), then append:

```python
@router.get("/place/{place_id}/children/geometry")
async def get_children_geometry(
    request: Request,
    place_id: str,
    indicator: str = Query(...),
    period: str | None = Query(default=None),
    child_type: str = Query(default="lsoa21"),
) -> dict[str, object]:
    """FeatureCollection of a place's sub-areas (default LSOAs) coloured by an
    indicator. A LATERAL join picks the latest period per child when `period`
    is omitted. Children without a value are excluded so the caller can detect
    'no sub-area data' (empty collection) and fall back to peer mode."""
    engine = request.app.state.engine
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT c.id, c.name,
                           ST_AsGeoJSON(ST_Simplify(c.geom, 0.005)) AS geojson,
                           iv.value
                    FROM geography.place_hierarchy h
                    JOIN geography.place c ON c.id = h.child_id
                    LEFT JOIN LATERAL (
                        SELECT v.value
                        FROM data.indicator_value v
                        WHERE v.place_id = c.id
                          AND v.indicator_key = :indicator
                          AND (:period IS NULL OR v.period = :period)
                        ORDER BY v.period DESC
                        LIMIT 1
                    ) iv ON TRUE
                    WHERE h.parent_id = :place_id
                      AND c.type = :child_type
                      AND c.geom IS NOT NULL
                    """
                ),
                {
                    "place_id": place_id,
                    "indicator": indicator,
                    "period": period,
                    "child_type": child_type,
                },
            )
        ).all()

    features: list[dict[str, object]] = []
    for r in rows:
        if r.value is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": _parse_geojson(r.geojson),
                "properties": {"id": r.id, "name": r.name, "value": float(r.value)},
            }
        )
    return {"type": "FeatureCollection", "features": features}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_place_geometry.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd server && uv run ruff format soundings/http/place_geometry.py tests/test_place_geometry.py && uv run ruff check soundings/http/place_geometry.py
cd .. && git add server/soundings/http/place_geometry.py server/tests/test_place_geometry.py
git commit -m "feat(api): sub-area children geometry endpoint for choropleths"
```

---

### Task 4: Endpoint — `GET /place/{id}/amenities/geometry`

**Files:**
- Modify: `server/soundings/http/place_geometry.py`
- Test: `server/tests/test_place_geometry.py`

**Interfaces:**
- Consumes: `request.app.state.adapter_registry.adapter_for_source("osm_overpass")` → an object exposing `amenity_locations(indicator_key, place_id)` (Task 2).
- Produces: route `GET /v1/place/{place_id}/amenities/geometry?indicators=k1,k2` → merged FeatureCollection across the requested amenity indicators.

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_place_geometry.py`:

```python
class _StubRegistry:
    def __init__(self, adapter: object) -> None:
        self._adapter = adapter

    def adapter_for_source(self, source_id: str) -> object:
        return self._adapter


class _StubOsmAdapter:
    async def amenity_locations(self, indicator_key: str, place_id: str) -> dict:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-1.5, 54.7]},
                    "properties": {"name": indicator_key, "layer": indicator_key},
                }
            ],
        }


async def test_amenities_geometry_merges_layers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.state, "adapter_registry", _StubRegistry(_StubOsmAdapter()))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/place/ltla24:E06000047/amenities/geometry",
            params={"indicators": "infrastructure.food_banks_count,infrastructure.schools_count"},
        )
    assert resp.status_code == 200
    fc = resp.json()
    layers = {f["properties"]["layer"] for f in fc["features"]}
    assert layers == {"infrastructure.food_banks_count", "infrastructure.schools_count"}
    assert len(fc["features"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_place_geometry.py -k amenities -v`
Expected: FAIL — 404.

- [ ] **Step 3: Implement the route**

Append to `place_geometry.py`:

```python
@router.get("/place/{place_id}/amenities/geometry")
async def get_amenities_geometry(
    request: Request,
    place_id: str,
    indicators: str = Query(..., description="comma-separated infrastructure.*_count keys"),
) -> dict[str, object]:
    """Merged FeatureCollection of OSM amenity point locations across the
    requested indicators. Per-indicator failures degrade to a partial
    collection rather than failing the whole request."""
    keys = [k.strip() for k in indicators.split(",") if k.strip()][:6]
    adapter = request.app.state.adapter_registry.adapter_for_source("osm_overpass")

    features: list[dict[str, object]] = []
    errors: list[str] = []
    for key in keys:
        try:
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

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m integration tests/test_place_geometry.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd server && uv run ruff format soundings/http/place_geometry.py tests/test_place_geometry.py && uv run ruff check soundings/http/place_geometry.py
cd .. && git add server/soundings/http/place_geometry.py server/tests/test_place_geometry.py
git commit -m "feat(api): amenities geometry endpoint merging OSM point layers"
```

---

### Task 5: Block schema — `granularity` + amenity overlay

**Files:**
- Modify: `server/soundings/ask/blocks.py`
- Test: `server/tests/test_ask_blocks.py`

**Interfaces:**
- Consumes: existing `MapBlock`, `MapOverlay` pydantic models and `AnswerBlock` union.
- Produces: `MapOverlay.source: Literal["amenities"]`, `MapOverlay.indicator_keys: list[str]` (min 1, max 6); `MapBlock.granularity: Literal["sub_areas", "peers"]` defaulting to `"peers"`.

- [ ] **Step 1: Write the failing tests**

Add to `server/tests/test_ask_blocks.py`:

```python
from soundings.ask.blocks import ComposeAnswerArgs


def test_map_block_accepts_granularity_and_amenity_overlay():
    args = ComposeAnswerArgs.model_validate(
        {
            "blocks": [
                {
                    "type": "map",
                    "place_id": "ltla24:E06000047",
                    "indicator_key": "deprivation.imd.score",
                    "granularity": "sub_areas",
                },
                {
                    "type": "map",
                    "place_id": "ltla24:E06000047",
                    "overlay": {
                        "source": "amenities",
                        "indicator_keys": ["infrastructure.food_banks_count"],
                    },
                },
            ]
        }
    )
    assert args.blocks[0].granularity == "sub_areas"
    assert args.blocks[1].overlay.indicator_keys == ["infrastructure.food_banks_count"]


def test_map_block_granularity_defaults_to_peers():
    args = ComposeAnswerArgs.model_validate(
        {"blocks": [{"type": "map", "place_id": "ltla24:E06000047", "indicator_key": "x"}]}
    )
    assert args.blocks[0].granularity == "peers"


def test_amenity_overlay_rejects_empty_indicator_keys():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ComposeAnswerArgs.model_validate(
            {
                "blocks": [
                    {
                        "type": "map",
                        "place_id": "ltla24:E06000047",
                        "overlay": {"source": "amenities", "indicator_keys": []},
                    }
                ]
            }
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest -m "not live and not integration" tests/test_ask_blocks.py -k "granularity or amenity" -v`
Expected: FAIL — `granularity`/`indicator_keys` unknown or not enforced.

- [ ] **Step 3: Update the schema**

In `blocks.py`, replace `MapOverlay` and add the field to `MapBlock`:

```python
class MapOverlay(BaseModel):
    # v1: amenity point locations only. air_quality/organisations had no point
    # data and were never implemented.
    source: Literal["amenities"]
    indicator_keys: list[str] = Field(min_length=1, max_length=6)


class MapBlock(BaseModel):
    type: Literal["map"]
    place_id: str
    indicator_key: str | None = None
    granularity: Literal["sub_areas", "peers"] = "peers"
    period: str | None = None
    caption: str | None = None
    overlay: MapOverlay | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest -m "not live and not integration" tests/test_ask_blocks.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd server && uv run ruff format soundings/ask/blocks.py tests/test_ask_blocks.py && uv run ruff check soundings/ask/blocks.py
cd .. && git add server/soundings/ask/blocks.py server/tests/test_ask_blocks.py
git commit -m "feat(ask): map block granularity + amenity overlay schema"
```

---

### Task 6: Prompt — teach the three map modes

**Files:**
- Modify: `server/soundings/ask/prompts.py`
- Test: `server/tests/test_ask_prompts.py`

**Interfaces:**
- Consumes: `_BLOCK_GUIDANCE` string in `prompts.py`.
- Produces: prompt text mentioning `granularity`, `sub_areas`, and the amenities overlay so the model emits the right map mode.

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_ask_prompts.py`:

```python
def test_prompt_teaches_three_map_modes():
    prompt = SystemPromptBuilder(mode="open").build()
    assert "granularity" in prompt
    assert "sub_areas" in prompt
    # points overlay for facility locations
    assert "indicator_keys" in prompt
    assert "where are" in prompt.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest -m "not live and not integration" tests/test_ask_prompts.py -k three_map_modes -v`
Expected: FAIL.

- [ ] **Step 3: Update the prompt**

In `prompts.py`, replace the `- map:` bullet inside `_BLOCK_GUIDANCE` with:

```python
- map: a map of a place. Three modes, chosen by fields:
  * boundary — just place_id (use to show where a place is).
  * choropleth — set indicator_key and granularity. Use granularity="sub_areas"
    for a within-place heatmap when the indicator has sub-area data (the
    deprivation.* family at LSOA, e.g. deprivation.imd.score); use
    granularity="peers" (default) to colour other places and show how this one
    ranks. "Where are the most deprived parts of X" → sub_areas.
  * points — set overlay {source:"amenities", indicator_keys:[...]} to plot real
    facility locations, colour-coded with a legend. Use for "where are the
    food banks / schools" questions, e.g. indicator_keys:
    ["infrastructure.food_banks_count","infrastructure.schools_count"]. Pair with
    the matching infrastructure.*_count indicators when the user also wants counts.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && uv run pytest -m "not live and not integration" tests/test_ask_prompts.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd server && uv run ruff format soundings/ask/prompts.py tests/test_ask_prompts.py && uv run ruff check soundings/ask/prompts.py
cd .. && git add server/soundings/ask/prompts.py server/tests/test_ask_prompts.py
git commit -m "feat(ask): prompt guidance for the three map modes"
```

---

### Task 7: UI — choropleth colour-scale fix + legend

**Files:**
- Modify: `ui/src/lib/map-renderer.ts`
- Test: `ui/src/lib/__tests__/map-renderer.test.ts` (create)

**Interfaces:**
- Consumes: existing `renderChoroplethMap` signature.
- Produces: exported pure helper `colourDomain(values: Array<number | null | undefined>): [number, number, number]` returning `[min, mid, max]` (nulls ignored; falls back to `[0, 0.5, 1]` when no finite values). `renderChoroplethMap` interpolates fill over that domain and renders a min–max legend.

- [ ] **Step 1: Write the failing test**

Create `ui/src/lib/__tests__/map-renderer.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { colourDomain } from "../map-renderer";

describe("colourDomain", () => {
  it("returns [min, mid, max] from finite values", () => {
    expect(colourDomain([10, 20, 30])).toEqual([10, 20, 30]);
  });

  it("ignores null/undefined/NaN", () => {
    expect(colourDomain([5, null, 15, undefined, NaN])).toEqual([5, 10, 15]);
  });

  it("falls back to [0, 0.5, 1] when no finite values", () => {
    expect(colourDomain([null, undefined])).toEqual([0, 0.5, 1]);
  });

  it("handles a single value (min === max)", () => {
    expect(colourDomain([7])).toEqual([7, 7, 7]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npx vitest run src/lib/__tests__/map-renderer.test.ts`
Expected: FAIL — `colourDomain` is not exported.

- [ ] **Step 3: Add `colourDomain` and use it in `renderChoroplethMap`**

In `map-renderer.ts`, add the exported helper near `computeBounds`:

```typescript
/** [min, mid, max] of the finite values, for a choropleth colour ramp.
 *  Falls back to [0, 0.5, 1] when there are no finite values. */
export function colourDomain(
  values: Array<number | null | undefined>,
): [number, number, number] {
  const finite = values.filter(
    (v): v is number => typeof v === "number" && Number.isFinite(v),
  );
  if (finite.length === 0) return [0, 0.5, 1];
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  return [min, (min + max) / 2, max];
}
```

Then in `renderChoroplethMap`, before `map.on("load", …)`, derive the domain from the features and use it in the `interpolate` expression. Replace the hardcoded stops:

```typescript
  const values = featureCollection.features.map(
    (f) => (f.properties?.[valueKey] as number | null | undefined),
  );
  const [domMin, domMid, domMax] = colourDomain(values);
```

and change the `fill-color` paint to:

```typescript
        "fill-color": [
          "interpolate",
          ["linear"],
          ["get", valueKey],
          domMin,
          stops[0],
          domMid,
          ACCENT_GREEN,
          domMax,
          stops[1],
        ],
```

Add a legend element to the container after `map.addControl(...)` (a simple absolutely-positioned gradient box):

```typescript
  const legend = document.createElement("div");
  legend.className = "map-legend choropleth-legend";
  legend.innerHTML =
    `<span class="legend-label">${escapeHtml(options.label ?? valueKey)}</span>` +
    `<span class="legend-gradient"></span>` +
    `<span class="legend-min">${domMin.toLocaleString("en-GB")}</span>` +
    `<span class="legend-max">${domMax.toLocaleString("en-GB")}</span>`;
  container.appendChild(legend);
```

(The `.map-legend` styles live in `ask.astro`; add them in Task 9.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npx vitest run src/lib/__tests__/map-renderer.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/map-renderer.ts ui/src/lib/__tests__/map-renderer.test.ts
git commit -m "fix(ui): derive choropleth colour scale from data + add legend"
```

---

### Task 8: UI — `renderAmenityMap` + label/legend helpers

**Files:**
- Modify: `ui/src/lib/map-renderer.ts`
- Test: `ui/src/lib/__tests__/map-renderer.test.ts`

**Interfaces:**
- Consumes: `PALETTE` (import from `./chart`), `renderPlaceMap`'s boundary paint approach, `colourDomain` (not needed here), MapLibre `circle` layers.
- Produces:
  - `amenityLayerLabel(indicatorKey: string): string` — `"infrastructure.food_banks_count"` → `"Food banks"`.
  - `amenityLegendItems(layers: string[]): Array<{ label: string; colour: string }>` — one item per layer, colour from `PALETTE` by index.
  - `renderAmenityMap(container: HTMLElement, boundary: GeoJSON.Feature, points: GeoJSON.FeatureCollection, options?: { tilesUrl?: string }): () => void`.

- [ ] **Step 1: Write the failing tests**

Add to `ui/src/lib/__tests__/map-renderer.test.ts`:

```typescript
import { amenityLayerLabel, amenityLegendItems } from "../map-renderer";
import { PALETTE } from "../chart";

describe("amenityLayerLabel", () => {
  it("humanises an infrastructure count key", () => {
    expect(amenityLayerLabel("infrastructure.food_banks_count")).toBe("Food banks");
    expect(amenityLayerLabel("infrastructure.gp_practices_count")).toBe("Gp practices");
  });
});

describe("amenityLegendItems", () => {
  it("assigns one PALETTE colour per layer", () => {
    const items = amenityLegendItems([
      "infrastructure.food_banks_count",
      "infrastructure.schools_count",
    ]);
    expect(items).toEqual([
      { label: "Food banks", colour: PALETTE[0] },
      { label: "Schools", colour: PALETTE[1] },
    ]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ui && npx vitest run src/lib/__tests__/map-renderer.test.ts`
Expected: FAIL — helpers not exported.

- [ ] **Step 3: Implement helpers + `renderAmenityMap`**

In `map-renderer.ts`, add `import { PALETTE } from "./chart";` at the top, then:

```typescript
/** "infrastructure.food_banks_count" → "Food banks". */
export function amenityLayerLabel(indicatorKey: string): string {
  const base = indicatorKey.replace(/^infrastructure\./, "").replace(/_count$/, "");
  const words = base.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function amenityLegendItems(
  layers: string[],
): Array<{ label: string; colour: string }> {
  return layers.map((layer, i) => ({
    label: amenityLayerLabel(layer),
    colour: PALETTE[i % PALETTE.length],
  }));
}

/**
 * Render a place boundary plus one colour-coded circle layer per amenity
 * `layer` property in `points`, with a legend and name popups. Returns a
 * cleanup function.
 */
export function renderAmenityMap(
  container: HTMLElement,
  boundary: GeoJSON.Feature,
  points: GeoJSON.FeatureCollection,
  options: { tilesUrl?: string } = {},
): () => void {
  const map = new maplibregl.Map(baseMapOptions(container, options.tilesUrl));

  const layers = Array.from(
    new Set(points.features.map((f) => String((f.properties ?? {}).layer ?? ""))),
  ).filter(Boolean);
  const colourByLayer = new Map(
    amenityLegendItems(layers).map((it, i) => [layers[i], it.colour]),
  );

  const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });

  map.on("load", () => {
    map.addSource("boundary", { type: "geojson", data: boundary });
    map.addLayer({
      id: "boundary-fill",
      type: "fill",
      source: "boundary",
      paint: { "fill-color": ACCENT_GREEN, "fill-opacity": 0.08 },
    });
    map.addLayer({
      id: "boundary-outline",
      type: "line",
      source: "boundary",
      paint: { "line-color": ACCENT_GREEN, "line-width": 1 },
    });

    map.addSource("amenities", { type: "geojson", data: points });
    for (const layer of layers) {
      map.addLayer({
        id: `amenity-${layer}`,
        type: "circle",
        source: "amenities",
        filter: ["==", ["get", "layer"], layer],
        paint: {
          "circle-radius": 5,
          "circle-color": colourByLayer.get(layer) ?? NAVY,
          "circle-stroke-color": CREAM,
          "circle-stroke-width": 1,
        },
      });
      map.on("mouseenter", `amenity-${layer}`, (e) => {
        const f = e.features?.[0];
        const props = (f?.properties ?? {}) as Record<string, unknown>;
        const name = (props.name as string | undefined) ?? amenityLayerLabel(layer);
        const coords = (f?.geometry as GeoJSON.Point | undefined)?.coordinates;
        popup.setHTML(
          `<div style="font-family:system-ui,sans-serif"><strong>${escapeHtml(name)}</strong><br/>${escapeHtml(amenityLayerLabel(layer))}</div>`,
        );
        if (coords) popup.setLngLat(coords as [number, number]).addTo(map);
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", `amenity-${layer}`, () => {
        popup.remove();
        map.getCanvas().style.cursor = "";
      });
    }

    map.fitBounds(featureBounds(boundary), { padding: 20 });
  });

  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

  const legend = document.createElement("div");
  legend.className = "map-legend amenity-legend";
  legend.innerHTML = amenityLegendItems(layers)
    .map(
      (it) =>
        `<span class="legend-item"><span class="legend-swatch" style="background:${it.colour}"></span>${escapeHtml(it.label)}</span>`,
    )
    .join("");
  container.appendChild(legend);

  return () => {
    popup.remove();
    map.remove();
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ui && npx vitest run src/lib/__tests__/map-renderer.test.ts`
Expected: PASS (helper tests; `renderAmenityMap` itself is MapLibre glue, not unit-tested — consistent with `renderPlaceMap`).

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/map-renderer.ts ui/src/lib/__tests__/map-renderer.test.ts
git commit -m "feat(ui): renderAmenityMap with colour-coded point layers + legend"
```

---

### Task 9: UI — wire `renderMapBlock` to the new modes + legend styles

**Files:**
- Modify: `ui/src/scripts/ask_page.ts`
- Modify: `ui/src/pages/ask.astro` (legend styles)

**Interfaces:**
- Consumes: `renderPlaceMap`, `renderChoroplethMap`, `renderAmenityMap` from `../lib/map-renderer`; the block fields `place_id`, `indicator_key`, `granularity`, `period`, `overlay`.
- Produces: an updated `renderMapBlock` that selects boundary / choropleth (sub_areas→peers fallback) / amenity-points based on block fields.

- [ ] **Step 1: Rewrite `renderMapBlock`**

Replace the body of `renderMapBlock` in `ask_page.ts` (the function near the `// map` section) with the branch logic below. Keep the existing `ensureMaplibreCss()`, `container` creation, and `caption` handling:

```typescript
        async function renderMapBlock(
          host: HTMLElement,
          block: { type: string; [k: string]: unknown },
          apiBase: string,
        ) {
          const mapPlaceId = asString(block.place_id);
          const indicatorKey = asStringOrUndef(block.indicator_key);
          const granularity = asStringOrUndef(block.granularity) ?? "peers";
          const period = asStringOrUndef(block.period);
          const caption = asStringOrUndef(block.caption);
          const overlay = block.overlay as
            | { source?: string; indicator_keys?: unknown }
            | undefined;
          if (!mapPlaceId) {
            showBlockError(host, "Map block missing place_id.");
            return;
          }
          ensureMaplibreCss();
          const container = document.createElement("div");
          container.className = "map-container";
          host.appendChild(container);

          try {
            const { renderPlaceMap, renderChoroplethMap, renderAmenityMap } =
              await import("../lib/map-renderer");

            // 1) amenity points take precedence when an overlay is present.
            if (overlay?.source === "amenities") {
              const keys = asStringArray(overlay.indicator_keys);
              if (keys.length === 0) {
                showBlockError(host, "Amenity overlay missing indicator_keys.");
                container.remove();
                return;
              }
              const [boundary, points] = await Promise.all([
                getJSON<GeoJSON.Feature>(
                  `/v1/place/${encodeURIComponent(mapPlaceId)}/geometry`,
                  apiBase,
                ),
                getJSON<GeoJSON.FeatureCollection>(
                  `/v1/place/${encodeURIComponent(mapPlaceId)}/amenities/geometry` +
                    `?indicators=${encodeURIComponent(keys.join(","))}`,
                  apiBase,
                ),
              ]);
              renderAmenityMap(container, boundary, points, {
                tilesUrl: mapTilesUrl || undefined,
              });
            } else if (indicatorKey && granularity === "sub_areas") {
              // 2) sub-area choropleth, falling back to peers if empty.
              let fc = await getJSON<GeoJSON.FeatureCollection>(
                `/v1/place/${encodeURIComponent(mapPlaceId)}/children/geometry` +
                  `?indicator=${encodeURIComponent(indicatorKey)}` +
                  (period ? `&period=${encodeURIComponent(period)}` : ""),
                apiBase,
              );
              if (!fc.features || fc.features.length === 0) {
                fc = await getJSON<GeoJSON.FeatureCollection>(
                  `/v1/place/${encodeURIComponent(mapPlaceId)}/peers/geometry` +
                    `?indicator=${encodeURIComponent(indicatorKey)}` +
                    (period ? `&period=${encodeURIComponent(period)}` : ""),
                  apiBase,
                );
              }
              renderChoroplethMap(container, fc, "value", {
                label: prettyKey(indicatorKey),
                tilesUrl: mapTilesUrl || undefined,
              });
            } else if (indicatorKey) {
              // 3) peer choropleth.
              const fc = await getJSON<GeoJSON.FeatureCollection>(
                `/v1/place/${encodeURIComponent(mapPlaceId)}/peers/geometry` +
                  `?indicator=${encodeURIComponent(indicatorKey)}` +
                  (period ? `&period=${encodeURIComponent(period)}` : ""),
                apiBase,
              );
              renderChoroplethMap(container, fc, "value", {
                label: prettyKey(indicatorKey),
                tilesUrl: mapTilesUrl || undefined,
              });
            } else {
              // 4) boundary only.
              const feature = await getJSON<GeoJSON.Feature>(
                `/v1/place/${encodeURIComponent(mapPlaceId)}/geometry`,
                apiBase,
              );
              renderPlaceMap(container, feature, { tilesUrl: mapTilesUrl || undefined });
            }
          } catch (err) {
            container.remove();
            showBlockError(
              host,
              "Could not load map: " + (err instanceof Error ? err.message : String(err)),
            );
            return;
          }

          if (caption) {
            const figcaption = document.createElement("p");
            figcaption.className = "map-caption text-muted text-small";
            figcaption.textContent = caption;
            host.appendChild(figcaption);
          }
        }
```

- [ ] **Step 2: Add legend styles to `ask.astro`**

In the `<style is:global>` block of `ui/src/pages/ask.astro`, add (next to the existing `.map-container` rule):

```css
    #answer-surface .map-container { position: relative; }
    #answer-surface .map-legend {
      position: absolute;
      bottom: var(--space-sm);
      left: var(--space-sm);
      background: rgba(250, 249, 246, 0.92);
      border: 1px solid var(--color-border-light);
      border-radius: var(--radius-sm);
      padding: var(--space-xs) var(--space-sm);
      font-size: var(--font-size-xs);
      display: flex;
      flex-direction: column;
      gap: 2px;
      z-index: 1;
    }
    #answer-surface .map-legend .legend-item {
      display: flex;
      align-items: center;
      gap: var(--space-xs);
    }
    #answer-surface .map-legend .legend-swatch {
      width: 10px;
      height: 10px;
      border-radius: 2px;
      display: inline-block;
    }
    #answer-surface .choropleth-legend .legend-gradient {
      display: block;
      width: 120px;
      height: 8px;
      border-radius: 2px;
      background: linear-gradient(to right, #faf9f6, #4a7c59, #1a2f4e);
    }
    #answer-surface .choropleth-legend .legend-min { float: left; }
    #answer-surface .choropleth-legend .legend-max { float: right; }
```

- [ ] **Step 3: Type-check + build the UI**

Run: `cd ui && npx astro check 2>&1 | tail -20 && npx astro build 2>&1 | tail -15`
Expected: no type errors in `ask_page.ts` / `map-renderer.ts`; build succeeds.

- [ ] **Step 4: Manual smoke test (real app)**

```bash
cd /Users/tomcwxyz/code/dataforaction-tom/soundings
docker compose -f infra/docker-compose.yml --project-directory . build server ui
docker compose -f infra/docker-compose.yml --project-directory . up -d server ui
# Warm + verify the new endpoints directly:
curl -s "http://127.0.0.1:8001/v1/place/ltla24:E06000047/children/geometry?indicator=deprivation.imd.score" | python3 -c "import sys,json;d=json.load(sys.stdin);print('children features:',len(d['features']))"
curl -s "http://127.0.0.1:8001/v1/place/ltla24:E06000047/amenities/geometry?indicators=infrastructure.food_banks_count,infrastructure.schools_count" | python3 -c "import sys,json;d=json.load(sys.stdin);print('amenity points:',len(d['features']))"
```
Expected: children features ≈ 330 (IMD per LSOA); amenity points > 0 (schools/food banks). Then open `http://127.0.0.1:4321/ask?q=Show%20me%20food%20banks%20and%20schools%20in%20County%20Durham&place_id=ltla24:E06000047` and confirm coloured points + legend; and an IMD sub-area question shows a graded choropleth.

- [ ] **Step 5: Commit**

```bash
git add ui/src/scripts/ask_page.ts ui/src/pages/ask.astro
git commit -m "feat(ui): render amenity points and sub-area choropleths on maps"
```

---

## Self-Review notes (addressed)

- **Spec coverage:** locations fetch (T1), adapter+cache (T2), children endpoint (T3), amenities endpoint (T4), schema (T5), prompt (T6), colour-scale fix (T7), renderAmenityMap+legend (T8), renderMapBlock wiring + styles (T9). Colour-scale bug, empty-vs-failure distinction, and budget-bypass are all covered.
- **Type consistency:** `amenity_locations` returns FeatureCollection dict (T2) consumed by the amenities endpoint (T4) and rendered via `renderAmenityMap` (T8/T9); `colourDomain` (T7) used only inside `renderChoroplethMap`; `amenityLegendItems`/`amenityLayerLabel` names match between T8 definition and T8/T9 use.
- **Deferred (per spec):** combined choropleth+points, air_quality/organisations overlays, location pre-warming.

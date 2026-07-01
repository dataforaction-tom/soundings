# National Choropleth Endpoint — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GET /v1/geographies/{place_type}/geometry` returning every area of a type coloured by an indicator (value + percentile + simplified geometry) — the national-view data source for the interactive-map explorer.

**Architecture:** A new read-only route in the existing `soundings/http/place_geometry.py` router. It mirrors the existing `peers/geometry` query but is not relative to a place (no self-exclusion). Latest-period fallback via `COALESCE`. Large layers (LSOA, ~35k features) are guarded behind an explicit `large=true` query flag.

**Tech Stack:** FastAPI, SQLAlchemy Core (`text`), PostGIS (`ST_Simplify`, `ST_AsGeoJSON`), pytest + httpx `ASGITransport` (integration, marked `@pytest.mark.integration`).

**Parent spec:** `docs/specs/2026-07-01-interactive-map-design.md` (increment 1).

## Global Constraints

- Python 3.12; mypy strict must stay clean.
- Integration tests use the `soundings_test` DB and the full app lifespan
  (`app.router.lifespan_context(app)`); they are marked `@pytest.mark.integration`
  and excluded from `make test`.
- Geometry is simplified with `ST_Simplify(geom, 0.005)` and serialised via
  `ST_AsGeoJSON`, matching the sibling endpoints.
- Percentile is derived from rank with the existing `_percentile_from_rank`
  helper (top = 100, bottom = 0).
- Conventional commits; never commit to `main` (work on `feat/interactive-map`).

## File Structure

- **Modify** `server/soundings/http/place_geometry.py` — add the
  `get_geographies_geometry` route alongside the existing geometry routes. Reuses
  the module's `_parse_geojson` and `_percentile_from_rank` helpers.
- **Modify** `server/tests/test_place_geometry.py` — add integration tests
  (reuses the existing `_seed_places_with_geometry` fixture).

---

### Task 1: National choropleth route (happy path)

**Files:**
- Modify: `server/soundings/http/place_geometry.py`
- Test: `server/tests/test_place_geometry.py`

**Interfaces:**
- Consumes: `request.app.state.engine`; module helpers `_parse_geojson(str|None) -> dict|None`, `_percentile_from_rank(rank: int|None, n: int) -> float|None`.
- Produces: `GET /v1/geographies/{place_type}/geometry?indicator=&period=&large=` →
  `{"type": "FeatureCollection", "features": [{"type":"Feature","geometry":..., "properties": {"id","name","value","percentile"}}]}` for every `geography.place` of `place_type`.

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_place_geometry.py` (the existing `_seed_places_with_geometry` seeds ltla24 places E06000001/E06000004/E06000005 with `population.total` period `2024`; Stockton E06000004 has geom, Darlington E06000005 has none):

```python
async def test_geographies_geometry_returns_all_areas_of_type() -> None:
    await _seed_places_with_geometry()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/v1/geographies/ltla24/geometry",
                params={"indicator": "population.total", "period": "2024"},
            )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["type"] == "FeatureCollection"
    # ALL ltla24 places (not peers-of-one) — nothing excluded.
    ids = {f["properties"]["id"] for f in body["features"]}
    assert ids == {"ltla24:E06000001", "ltla24:E06000004", "ltla24:E06000005"}
    by_id = {f["properties"]["id"]: f["properties"] for f in body["features"]}
    assert by_id["ltla24:E06000004"]["value"] == 200
    # Darlington has no geom → geometry null but still present.
    darlington = next(f for f in body["features"] if f["properties"]["id"] == "ltla24:E06000005")
    assert darlington["geometry"] is None


async def test_geographies_geometry_defaults_to_latest_period_when_omitted() -> None:
    await _seed_places_with_geometry()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/v1/geographies/ltla24/geometry",
                params={"indicator": "population.total"},  # no period
            )
    assert response.status_code == 200, response.text
    by_id = {f["properties"]["id"]: f["properties"] for f in response.json()["features"]}
    assert by_id["ltla24:E06000004"]["value"] == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_place_geometry.py::test_geographies_geometry_returns_all_areas_of_type -m integration -v`
Expected: FAIL — 404 (route not defined) / assertion error.

- [ ] **Step 3: Write the route**

Add to `server/soundings/http/place_geometry.py` (after `get_children_geometry`, before `get_amenities_geometry`):

```python
@router.get("/geographies/{place_type}/geometry")
async def get_geographies_geometry(
    request: Request,
    place_type: str,
    indicator: str = Query(...),
    period: str | None = Query(default=None),
    large: bool = Query(default=False),
) -> dict[str, object]:
    """GeoJSON FeatureCollection of ALL places of `place_type`, coloured by an
    indicator (value + percentile). The national counterpart to
    `peers/geometry` (which is relative to one place). Latest period per place
    when `period` is omitted. Large layers (lsoa21) require `large=true`."""
    if place_type == "lsoa21" and not large:
        raise HTTPException(
            status_code=422,
            detail="lsoa21 is a large layer; pass large=true to confirm",
        )
    engine = request.app.state.engine
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    WITH area_values AS (
                        SELECT p.id, p.name, iv.value
                        FROM geography.place p
                        LEFT JOIN LATERAL (
                            SELECT v.value
                            FROM data.indicator_value v
                            WHERE v.place_id = p.id
                              AND v.indicator_key = :indicator
                              AND (COALESCE(:period, v.period) = v.period)
                            ORDER BY v.period DESC
                            LIMIT 1
                        ) iv ON TRUE
                        WHERE p.type = :place_type
                    ),
                    ranked AS (
                        SELECT av.*,
                               RANK() OVER (ORDER BY av.value DESC NULLS LAST) AS rank,
                               COUNT(av.value) OVER () AS n_with_values
                        FROM area_values av
                    )
                    SELECT r.id, r.name, r.value, r.rank, r.n_with_values,
                           ST_AsGeoJSON(ST_Simplify(p.geom, 0.005)) AS geojson
                    FROM ranked r
                    JOIN geography.place p ON p.id = r.id
                    """
                ),
                {"place_type": place_type, "indicator": indicator, "period": period},
            )
        ).all()

    features: list[dict[str, object]] = []
    for r in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": _parse_geojson(r.geojson),
                "properties": {
                    "id": r.id,
                    "name": r.name,
                    "value": float(r.value) if r.value is not None else None,
                    "percentile": _percentile_from_rank(r.rank, r.n_with_values),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_place_geometry.py -k geographies_geometry -m integration -v`
Expected: PASS (both happy-path + latest-period tests).

- [ ] **Step 5: mypy + commit**

Run: `cd server && uv run mypy soundings/http/place_geometry.py`
Expected: `Success: no issues found`.

```bash
git add server/soundings/http/place_geometry.py server/tests/test_place_geometry.py
git commit -m "feat(map): national choropleth endpoint /v1/geographies/{type}/geometry"
```

---

### Task 2: Large-layer (LSOA) guard

**Files:**
- Modify: `server/tests/test_place_geometry.py` (route already handles the guard from Task 1)

**Interfaces:**
- Consumes: the route from Task 1.
- Produces: confirmation that `place_type=lsoa21` returns 422 without `large=true`, and 200 with it.

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_place_geometry.py`. Reuse `_seed_parent_with_lsoa_children` (seeds `lsoa21` children with a `deprivation.imd.score`-style value — check the fixture's indicator key and use it):

```python
async def test_geographies_geometry_guards_large_lsoa_layer() -> None:
    await _seed_parent_with_lsoa_children()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            blocked = await ac.get(
                "/v1/geographies/lsoa21/geometry",
                params={"indicator": "deprivation.imd.score"},
            )
            allowed = await ac.get(
                "/v1/geographies/lsoa21/geometry",
                params={"indicator": "deprivation.imd.score", "large": "true"},
            )
    assert blocked.status_code == 422
    assert allowed.status_code == 200
```

Note: confirm the indicator key seeded by `_seed_parent_with_lsoa_children` (read the fixture) and use that exact key in both requests.

- [ ] **Step 2: Run test to verify current behaviour**

Run: `cd server && uv run pytest tests/test_place_geometry.py::test_geographies_geometry_guards_large_lsoa_layer -m integration -v`
Expected: PASS if the fixture indicator key is correct (the guard shipped in Task 1). If it FAILs on the key, fix the key in the test to match the fixture, then re-run.

- [ ] **Step 3: Commit**

```bash
git add server/tests/test_place_geometry.py
git commit -m "test(map): guard national LSOA layer behind large=true"
```

---

## Self-Review

- **Spec coverage:** increment 1 = "national choropleth endpoint" with value +
  percentile, simplified geometry, latest-period fallback, LSOA guard → all
  covered by Task 1 (route + happy path + period fallback) and Task 2 (guard).
- **Placeholder scan:** none — full SQL and test code inline. One explicit
  instruction to verify the fixture's indicator key against the codebase (not a
  placeholder — a codebase-specific lookup the implementer must confirm).
- **Type consistency:** route returns `dict[str, object]`; helpers
  `_parse_geojson` / `_percentile_from_rank` used with their existing signatures;
  properties keys (`id`,`name`,`value`,`percentile`) match `peers/geometry`.

## Out of scope (later increments)

- `InteractiveMap` component refactor (increment 2).
- Explorer page, point-layer toggles, side panel, LSOA drill-down (increments 3–6).

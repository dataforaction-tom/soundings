# Green Spaces — Implementation Plan

**Date:** 2026-06-30
**Status:** Draft — for build
**Parent:** PLAN.md — Phase 6b (breadth, NDL data-source expansion)
**Track:** Second Phase 6b source group. New domain: **Environment** (greenspace).

## Objective

Add green-space indicators at **LSOA (neighbourhood) and LTLA** level. This is
also the second LSOA-level dataset in the system (after deprivation), so it
lights up neighbourhood choropleths for a new domain.

## Sources (all open — licences verified 2026-06-30)

| # | Source | Licence | Access | Geography | Build |
|---|--------|---------|--------|-----------|-------|
| A | **OS Open Greenspace** | OGL v3.0 | Bulk GeoPackage (anon) | Site polygons (EPSG:27700) → aggregate to LSOA/LTLA | **First** |
| B | **FoE Green Space Consolidated v2.1** | OGL v3.0 / Open Parliament Licence | Excel (.xlsx) | Neighbourhood (ONS) | Follow-up |
| C | **FoE / Terra Sulis Woodland Opportunity** | CC-BY-4.0 | (verify) | Spatial | Optional follow-up |

Licence note: OS requires the attribution "Contains OS data © Crown copyright
and database right [year]". FoE Green Space Consolidated is OGL/OPL per the FoE
near-you data portal (the all-rights-reserved terms on `policy.friendsoftheearth.uk`
do NOT apply to these openly-licensed datasets). Woodland Opportunity is CC-BY-4.0
(attribution: Tim Richards / Terra Sulis).

Avoid: the aggregated "Near you LA data v7.0.0" CSV — mixed licence including
CC-BY-**NC**-SA (non-commercial), not open.

## Dependencies (approved)

Add `geopandas` + `pyogrio` for GeoPackage reading. Requires GDAL/GEOS system
libs in `infra/Dockerfile.server`. (User approved adding these.)

---

## Build A — OS Open Greenspace (first PR)

### Approach

1. **Client** — download the GB-wide OS Open Greenspace GeoPackage via the OS
   Downloads API (anonymous for OpenData products:
   `https://api.os.uk/downloads/v1/products/OpenGreenspace/downloads`), pick the
   GeoPackage, stream to a temp file. Read the `GreenspaceSite` layer with
   geopandas/pyogrio.
2. **Stage** — load site polygons into a new `geography.greenspace_site` table:
   `(id, function, name, geom geometry(MULTIPOLYGON, 4326))`, reprojecting
   27700→4326 on the way in (match `geography.place.geom`). GiST index on geom.
3. **Aggregate** — per place (LSOA + LTLA), spatial-join greenspace polygons to
   `geography.place.geom` and sum intersected area in m² via
   `ST_Area(ST_Intersection(gs.geom, p.geom)::geography)`, with an
   `ST_Intersects` prefilter so the GiST index does the heavy lifting. Counts by
   `function` for the park/playing-field indicators.
4. **UPSERT** indicator values (period = YYYY-MM of the load).

### Indicators (new `environment` domain entries)

```
environment.greenspace.area_hectares          # total greenspace area in place
environment.greenspace.area_pct               # greenspace area / place area
environment.greenspace.public_park_count      # function = Public Park Or Garden
environment.greenspace.area_sqm_per_1000       # per 1,000 resident population
```

`available_at: ["lsoa21", "ltla24", "utla24"]`. Caveats: registered green-space
*sites* only (not all informal/private green space); area clipped to place
boundary.

### TDD tasks (Build A)

1. **Deps + Docker** — add `geopandas`/`pyogrio` to `server/pyproject.toml`;
   add GDAL/GEOS to `infra/Dockerfile.server`; `uv lock`. Verify import in a
   throwaway test. Commit: `chore: add geopandas for geospatial ingestion`.
2. **Migration** — `geography.greenspace_site` table + GiST index. Commit:
   `feat(greenspace): greenspace_site table`.
3. **Client** — download + read GeoPackage `GreenspaceSite` layer → iterator of
   `{id, function, name, geom_wkt/geojson}`. Test with a tiny in-memory/temp
   GeoPackage fixture (geopandas can write one). Commit:
   `feat(greenspace): OS Open Greenspace GeoPackage client`.
3. **Loader — stage + aggregate** (integration, test DB). Seed 1–2 LSOAs with
   real-ish boundary polygons + a couple of greenspace polygons; assert area /
   pct / park-count aggregates. Commit: `feat(greenspace): per-place spatial aggregation`.
4. **Catalogue + registration** — environment greenspace indicators + source
   entry; register loader in `loader/run.py`. Commit:
   `feat(greenspace): catalogue + loader registration`.
5. **Live smoke** (`@pytest.mark.live`) — OS Downloads API alive + GeoPackage
   opens + has the expected layer/columns; read a small slice. Commit:
   `test(greenspace): live OS download smoke`.
6. **Docs** — STATE/PLAN. Commit: `docs: greenspace loader shipped`.

### Scale / cost

GB greenspace is a modest vector set (~tens of MB GeoPackage). The intersection
against 35k LSOAs with a GiST prefilter is a batch-loader operation (minutes),
acceptable for a 6-monthly source. seed-light restricts to seeded places.

---

## Build B — FoE Green Space Consolidated v2.1 (follow-up PR)

Excel loader (we already parse spreadsheets elsewhere). Neighbourhood-level
green-space access / garden-coverage / "lacks both green space and gardens"
flag → `environment.greenspace.access_*` indicators at LSOA. Verify the exact
geography (LSOA vs MSOA) and columns from the file before building. Lighter than
Build A; directly enriches neighbourhood choropleths.

## Build C — Woodland Opportunity (optional)

CC-BY-4.0 spatial dataset of woodland-creation potential (not current canopy).
Spatial aggregation like Build A. Lower priority — measures opportunity, not
current state. Verify download format first.

## Out of scope

- Tree-canopy %: no clean open source (FoE policy canopy spreadsheet is
  all-rights-reserved; deriving from EA LiDAR is a large separate effort).
- ward/constituency boundaries (separate geometry-loading follow-up).

## Verification

`make test` + `make test-integration` green; mypy strict; live smoke green;
local: a greenspace LSOA choropleth renders on the map for a seeded LTLA.

# Give Food as the food-bank data source — design

> Date: 2026-06-26
> Builds on: the map-data-rendering feature (2026-06-26-map-data-rendering)
> Status: approved design, pending implementation plan

## Problem

Food banks are currently sourced from OpenStreetMap via the
`infrastructure.food_banks_count` indicator (Overpass `amenity=food_bank` +
`social_facility=food_bank`). For County Durham this returns **1** — verified
to be genuine OSM under-mapping, not a bug:

- Our tags are the correct standard OSM food-bank tags; the query mechanism is
  sound (schools returns 548 for the same place).
- Broadening to `amenity=social_facility` returns 184, but that is *all* social
  facilities (care homes, shelters), not food banks; `social_facility:for=food`
  is 0. There is no tag that recovers food banks without over-counting.

[Give Food](https://www.givefood.org.uk/) maintains the UK's largest public
food-bank database (~2,992 location records, daily-updated). Its bulk dump for
County Durham contains **41 food-bank locations** vs OSM's 1.

## Goal

Make Give Food the authoritative source for food banks — accurate counts per
place and real distribution-location pins on the map — replacing OSM for this
one amenity while leaving OSM as the source for all other amenities.

Scope (confirmed): **counts per place** and **map locations (points)**. NOT in
v1: per-food-bank "needs" data.

Count unit (confirmed): **distribution locations** (the dump's location-level
rows), not food-bank organisations.

## What Give Food provides (verified)

- Bulk dump `GET /dumps/foodbanks/json/latest/` — one HTTP call, JSON, ~2,992
  rows, ~12 MB, updated daily. **2,992 rows across 1,024 organisations**, so the
  dump is location-level (multiple rows per org).
- Each row carries: `lat_lng` ("54.87,-1.58"), `postcode`, **pre-resolved
  `lsoa`** (ONS GSS code, e.g. `E01023910`), `msoa`, `ward`,
  `parliamentary_constituency`, `district` (names), `organisation_name`,
  `location_name`, plus charity/contact fields we don't need.
- No API key required. Terms require attribution ("credit us with a link") and
  keeping data fresh; we satisfy attribution via the existing sources footer.

## Non-goals (v1)

- "Needs" / shopping-list data (a different shape; would require linking to each
  food bank's shopping-list URL per their terms). Deferred.
- Per-organisation aggregation or the `/api/2/locations/` endpoint. The bulk
  dump is the single source.
- Backfilling Scotland/NI differently — Give Food covers UK; counts follow
  whatever places a location's coordinates fall within.

## Architecture

A new **`givefood` passthrough source** with a `GiveFoodAdapter`, mirroring the
existing OSM/OpenAQ passthrough adapters.

- `GiveFoodClient.fetch_foodbanks() -> list[dict]` — GET the dump with a
  `User-Agent` header; return each row trimmed to the fields we use:
  `{lat: float, lng: float, postcode: str|None, lsoa: str|None,
  name: str, org: str|None}` (name = `location_name` or, if blank,
  `organisation_name`; `lat`/`lng` parsed from `lat_lng`). Raise on HTTP/parse
  failure.
- `GiveFoodAdapter(PassthroughAdapter)`:
  - `_cached_dump()` → returns the trimmed list, cached under
    `givefood:foodbanks:all` (TTL 24h). A transport failure propagates (never
    caches an empty list) — same rule as the OSM adapter.
  - `fetch_indicator("infrastructure.food_banks_count", place_id, period)` →
    count of dump locations whose `lat_lng` falls within the place polygon
    (point-in-polygon, below); returns an `IndicatorValue`, cached per place
    under `givefood:count:{place_id}` (TTL 24h).
  - `amenity_locations("infrastructure.food_banks_count", place_id) -> dict |
    None` → GeoJSON FeatureCollection of the matching locations (same shape the
    map renderer already consumes); `None` for any non-food-bank indicator key.

**Food banks become a Give Food indicator.** In `catalogue/indicators.yaml`,
re-point `infrastructure.food_banks_count` from `source_id: osm_overpass` to
`source_id: givefood`, and update its description + caveats. The orchestrator
routes counts by catalogue `source_id`, so the count path switches over with no
orchestrator change. Remove `infrastructure.food_banks_count` from the OSM
adapter's `INDICATOR_TAGS` so OSM returns `None` for it (retired).

**Endpoint generalisation.** `GET /place/{id}/amenities/geometry` currently
hardcodes `adapter_for_source("osm_overpass")`. Make it **source-aware**: for
each requested indicator, look up its catalogue `source_id` and resolve that
adapter via the registry, then call `amenity_locations`. Both OSM and Give Food
implement that method, so one map can mix food banks (Give Food) with schools /
GPs (OSM). This removes the hardcoding rather than special-casing food banks.

## Geography matching — point-in-polygon

Primary matcher is **point-in-polygon on `lat_lng`** (refined from an initial
LSOA-hierarchy idea): uniform across every place level (LSOA, LTLA, ward,
constituency) with no dependence on `place_hierarchy` carrying ward/constituency
links, and it is the same "points inside this boundary" filter the map needs.
The query mirrors `GeographyService.find_containing_places_by_point`:

```sql
SELECT count(*)
FROM unnest(:lngs ::float8[], :lats ::float8[]) AS p(lng, lat),
     geography.place g
WHERE g.id = :place_id
  AND g.geom IS NOT NULL
  AND ST_Within(ST_SetSRID(ST_Point(p.lng, p.lat), 4326), g.geom)
```

For `amenity_locations` the same predicate selects the rows to emit as points.
Fallback: a row with a missing/unparseable `lat_lng` but a valid `lsoa` is
matched by joining its `lsoa` GSS code to `geography.place_hierarchy`
(`child_id = 'lsoa21:'||lsoa`, ancestor `parent_id = :place_id`); rows with
neither are dropped with a count caveat.

## Data flow (end to end)

1. First read for any place triggers `_cached_dump()` → one dump fetch (12 MB),
   cached 24h. Subsequent reads (any place) hit the warm dump cache.
2. Count: load dump → ST_Within count against the place geom → `IndicatorValue`,
   cached per place.
3. Map: `/amenities/geometry?indicators=infrastructure.food_banks_count` →
   source-aware dispatch → Give Food `amenity_locations` → GeoJSON points →
   `renderAmenityMap`.
4. Mixed map (`…food_banks_count,infrastructure.schools_count`): food banks via
   Give Food, schools via OSM, merged into one FeatureCollection.

## Pre-warming

`givefood` source gets a daily `refresh_cadence`. `GiveFoodAdapter.
pre_warm_for_places(place_ids)` warms the dump once, then the per-LTLA counts,
so user reads stay on a warm cache. The dump fetch is the only slow step;
per-place ST_Within queries are fast.

## Error handling

- Dump unreachable → `fetch_foodbanks` raises → `fetch_indicator` /
  `amenity_locations` propagate → orchestrator caveat / block error. Never
  cached as zero (mirrors the OSM `OverpassUnavailableError` discipline).
- A place with no geometry → empty FeatureCollection / no count (caveat),
  same as the OSM adapter's no-bbox path.

## Attribution & licensing

Give Food asks for a credit link. The `catalogue.source` row sets
`label: "Give Food"`, `publisher: "Give Food"`,
`publisher_url: "https://www.givefood.org.uk/"`, and the existing sources
footer renders the linked source — satisfying attribution. Licence field notes
"Give Food terms — attribution required". The indicator's caveat states the
source and that it is daily-updated.

## Testing

- **Client unit** (mock httpx): `fetch_foodbanks` parses the dump into trimmed
  records, parses `"lat,lng"` into floats, sends the User-Agent, and raises on
  HTTP error.
- **Adapter integration** (test DB; seed one place polygon + a canned dump via a
  fake client with locations inside *and* outside the boundary):
  - `fetch_indicator` counts only in-boundary locations (ST_Within); ignores
    outside ones.
  - `amenity_locations` returns GeoJSON points for in-boundary locations only,
    each with `name` + `layer` properties and `[lng, lat]` coordinates.
  - second call served from cache (no second upstream fetch).
  - transport failure raises and is **not** cached.
  - a row with missing `lat_lng` but valid `lsoa` is matched by the fallback.
- **Endpoint integration** (`/amenities/geometry`): source-aware dispatch — a
  stub registry proves `infrastructure.food_banks_count` invokes the Give Food
  adapter and `infrastructure.schools_count` invokes OSM, and the two layers
  merge into one FeatureCollection.
- **Catalogue + retirement**: after re-point,
  `infrastructure.food_banks_count.source_id == "givefood"`, and OSM's
  `amenity_locations("infrastructure.food_banks_count", …)` returns `None`.
- **Orchestrator count path**: `get_indicators(["infrastructure.food_banks_count"])`
  routes to Give Food and returns the seeded in-boundary count.

## Files touched (summary)

New:
- `server/soundings/adapters/givefood/__init__.py`
- `server/soundings/adapters/givefood/client.py` — `GiveFoodClient`
- `server/soundings/adapters/givefood/adapter.py` — `GiveFoodAdapter`
- `server/tests/test_givefood_client.py`, `test_givefood_adapter.py`

Modified:
- `catalogue/sources.yaml` — add `givefood` source (passthrough, daily cadence)
- `catalogue/indicators.yaml` — re-point `infrastructure.food_banks_count` to
  `givefood`; update description + caveats
- `server/soundings/app.py` — register `GiveFoodAdapter`
- `server/soundings/adapters/osm_overpass/adapter.py` — drop `food_banks` from
  `INDICATOR_TAGS`
- `server/soundings/http/place_geometry.py` — source-aware `/amenities/geometry`
- `server/tests/test_place_geometry.py`, `test_osm_overpass_adapter.py`,
  a catalogue test — updated for the re-point + source-aware dispatch

## Open questions / risks

- **Dump size (12 MB) in one cache row.** Trimming to ~6 fields per row cuts
  this substantially; if the trimmed payload is still large, the
  `cache.source_cache` JSONB row is acceptable (Postgres TOAST handles it), but
  worth confirming the trimmed size during implementation.
- **Org vs location ambiguity in Give Food's data.** The foodbanks dump (2,992
  rows) is the documented bulk export and the count unit we use; Give Food also
  exposes `/api/2/locations/` (1,968) and per-org `locations` arrays with
  different totals. We standardise on the dump and describe the indicator as
  "Give Food food-bank locations" to avoid implying a different denominator.
- **Coordinate accuracy.** Point-in-polygon trusts Give Food's `lat_lng`; a
  mis-geocoded row could land in the wrong place. Acceptable for v1; the `lsoa`
  fallback and Give Food's own geocoding quality mitigate it.

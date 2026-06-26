# Map data rendering — design

> Date: 2026-06-26
> Branch context: follows `feat/slice-1-chart-renderers`
> Status: approved design, pending implementation plan

## Problem

A `map` block in the Ask answer currently only ever renders a place **boundary**.
It cannot show the data a question is really about:

- "Show me the food banks and schools in County Durham" → we can only draw the
  outline; we cannot show *where* they are.
- "Show me the IMD data" → no deprivation map; the IMD value exists only as a
  single number on a card.

There is a half-built peer choropleth path (`/place/{id}/peers/geometry` +
`renderChoroplethMap`), but it is not exposed as a usable mode and its colour
scale is broken (see Known bug below).

## Goal

Make one `map` block support three layered capabilities, chosen by fields the
model sets, so maps render data — point locations and indicator choropleths —
not just boundaries.

| Mode | Draws | Data source |
|------|-------|-------------|
| **boundary** (exists) | place outline | `GET /place/{id}/geometry` |
| **choropleth** | sub-areas *or* peers coloured by an indicator | new `GET /place/{id}/children/geometry` **or** existing `GET /place/{id}/peers/geometry` |
| **points** | amenity locations as colour-coded markers + legend | new `GET /place/{id}/amenities/geometry` (OSM live + cached) |

Points always draw the **boundary** underneath. A choropleth replaces the
boundary fill. In v1, choropleth and points are not combined in a single block:
if a block sets both `indicator_key` and `overlay`, **points take precedence**
(boundary + points). Layering points on top of a choropleth fill is a noted
future enhancement (see Non-goals).

## Non-goals (v1)

- `air_quality` and `organisations` map overlays. The old `MapOverlay.source`
  enum listed them but they were never implemented and we have no point
  coordinates for them (sensors lack stored lat/lng; charities store only a
  registered-address `place_id`, not coordinates). Narrow the enum to
  `amenities` and defer the rest.
- Pre-warming amenity **locations**. Counts pre-warming stays as-is; locations
  are fetched on demand and cached (justified below).
- Choosing colour direction by `higher_is` (better/worse). v1 uses a single
  low→high ramp and relies on the legend + caption for interpretation.
- Combining a choropleth fill and a points overlay in the same block. The
  schema permits both fields, but v1 renders points-with-boundary when both are
  set (points take precedence). Layering points over a choropleth fill is a
  future enhancement.

## Key architectural insight: map endpoints bypass the soft budget

The indicator fan-out in `IndicatorOrchestrator.fetch` has a 10s soft budget
that cancels slow adapters. The map data endpoints described here are called
**directly from the browser** (`ask_page.ts` → `fetch`), not through that
fan-out. So a first, uncached Overpass location query can take the full
Overpass time and then cache — there is no budget-cancellation problem for
maps. This is why on-demand location fetching is acceptable without
pre-warming.

## Backend

### OSM client — add location fetch (`adapters/osm_overpass/client.py`)

New method `locations_by_tag(tag_key, tag_value, bbox) -> list[dict]`:

- Same query shape as `count_by_tag` but emits `out center tags;` instead of
  `out count;`. Nodes carry `lat`/`lon` directly; ways/relations carry a
  `center: {lat, lon}`. The element `tags.name` becomes the point label.
- Returns a list of `{"lat": float, "lng": float, "name": str | None}`.
- Reuses the hardened transport added in `fix(osm)`: `OVERPASS_HEADERS`
  (User-Agent + Accept), primary `overpass-api.de` + fallback `kumi.systems`,
  and raises `OverpassUnavailableError` when no endpoint yields a usable
  response.
- **Empty vs failure distinction:** an empty `elements` list is a *valid*
  "no amenities here" and returns `[]`. Only transport/parse failure on all
  endpoints raises. So we never plot nothing-as-error or cache error-as-nothing.
- Caps results at a sane maximum (e.g. 1000 points) to bound the payload;
  logs/notes when the cap truncates.

### OSM adapter — new method (`adapters/osm_overpass/adapter.py`)

New `amenity_locations(indicator_key, place_id) -> dict` (GeoJSON
FeatureCollection):

- Resolves the place bbox via the existing `_get_bbox` (PostGIS).
- For the indicator's tag set (`INDICATOR_TAGS[indicator_key]`), calls
  `locations_by_tag` per tag and merges, de-duplicating by rounded
  (lat, lng).
- Each feature: `{"type": "Feature", "geometry": Point[lng, lat],
  "properties": {"name": str | None, "layer": indicator_key}}`.
- Caches the FeatureCollection under `osmgeo:{indicator_key}:{place_id}` with
  the same 30-day TTL as counts. A transport failure propagates (not cached),
  consistent with the count path.
- Returns `None` for an unknown indicator key (not an amenity indicator).

### New endpoints (`http/place_geometry.py`)

**`GET /place/{place_id}/children/geometry`**
Query params: `indicator` (required), `period` (optional),
`child_type` (default `lsoa21`).

- Joins `geography.place_hierarchy` (parent = `place_id`) → child places of
  `child_type` → their `ST_Simplify(geom, 0.005)` and a left join on
  `data.indicator_value` for `indicator`/`period`.
- Returns a FeatureCollection; each feature
  `properties = {id, name, value}`.
- If no child carries a value for the indicator (e.g. an LTLA-only
  indicator), returns an empty FeatureCollection so the client can fall back
  to peer mode. (County Durham → 330 LSOA features with IMD, confirmed.)

**`GET /place/{place_id}/amenities/geometry`**
Query param: `indicators` (comma-separated `infrastructure.*_count` keys,
1–6).

- For each requested indicator, fetches the adapter's
  `amenity_locations(indicator, place_id)` and merges the features into one
  FeatureCollection (each feature keeps its `layer` property), so a single map
  can show food banks **and** schools together.
- Per-indicator failures degrade to a partial collection with a note rather
  than failing the whole request.

## Frontend (`lib/map-renderer.ts`, `scripts/ask_page.ts`)

### Fix the choropleth colour scale (known bug)

`renderChoroplethMap` interpolates `["get", valueKey]` over a hardcoded
`0 → 0.5 → 1`. Real values (IMD ≈ 5–40, counts in the hundreds) all clamp to
the top stop, so every polygon renders the same colour.

Fix: extract a pure helper `colourDomain(values: number[]) -> [min, mid, max]`
(nulls ignored, `mid` = midpoint) and interpolate the fill across that domain.
Add a small gradient **legend** (min–max with the indicator label).

### New `renderAmenityMap` (`map-renderer.ts`)

`renderAmenityMap(container, boundaryFeature, pointsFC, options)`:

- Draws the boundary (reusing the existing fill + outline paint).
- Adds one MapLibre **circle layer per `layer` value** in the points
  FeatureCollection, each a distinct `PALETTE` colour.
- Adds a **legend** (swatch + human label per amenity type, e.g.
  🟢 Food banks, 🔵 Schools) using the same `PALETTE` as the chart legends.
- Hover/click **popup** showing each point's `name` (falls back to the amenity
  type when unnamed).
- Returns a cleanup function (`map.remove()` + popup teardown), matching the
  existing renderers.

### Rewrite `renderMapBlock` (`ask_page.ts`)

Branch on the block fields, in precedence order:

1. `overlay?.source === "amenities"` → fetch `/amenities/geometry?indicators=…`
   + the boundary → `renderAmenityMap`. Takes precedence if `indicator_key` is
   also set (v1 does not layer choropleth + points).
2. `indicator_key` + `granularity === "sub_areas"` → fetch
   `/children/geometry`; if empty, fall back to `/peers/geometry` with a
   caveat → `renderChoroplethMap`.
3. `indicator_key` (default `granularity === "peers"`) → existing
   `/peers/geometry` → `renderChoroplethMap`.
4. else → boundary (`renderPlaceMap`, unchanged).

All new legends use the Good Ship `PALETTE`, consistent with the composition
chart legend.

## Block schema (`ask/blocks.py`)

```python
class MapOverlay(BaseModel):
    source: Literal["amenities"]              # narrowed from air_quality/organisations
    indicator_keys: list[str] = Field(min_length=1, max_length=6)
    # infrastructure.*_count layers to plot, e.g.
    # ["infrastructure.food_banks_count", "infrastructure.schools_count"]

class MapBlock(BaseModel):
    type: Literal["map"]
    place_id: str
    indicator_key: str | None = None          # choropleth indicator (unchanged)
    granularity: Literal["sub_areas", "peers"] = "peers"   # NEW
    period: str | None = None
    caption: str | None = None
    overlay: MapOverlay | None = None         # points overlay
```

The three modes map onto fields. A block may set both `indicator_key` and
`overlay`, but in v1 the renderer treats points as taking precedence (see
Frontend precedence order); combined choropleth + points rendering is deferred.

## Prompt (`ask/prompts.py`)

Rewrite the `map` block guidance to teach the three modes:

- *"Where are the X"* (facilities) → `overlay: {source: "amenities",
  indicator_keys: [...]}`. Plots real OSM locations, colour-coded with a
  legend. Use for food banks, schools, GPs, etc.
- *"How deprived / how varied is X across the area"* → `indicator_key` +
  `granularity: "sub_areas"` → an LSOA heatmap. Only for indicators with
  sub-area data (the deprivation family); name those in the prompt.
- *"How does X compare to other places"* → `indicator_key` +
  `granularity: "peers"` (default).

Tie it to the existing OSM amenity-count routing: when a facility question also
wants counts, pair the amenities overlay with the matching
`infrastructure.*_count` indicators.

## Testing

- **Backend unit** (`test_osm_overpass_client.py`): `locations_by_tag` against
  `MockTransport` — parses `out center` for node + way/relation centroids,
  names from tags; empty `elements` → `[]`; both-endpoints-fail → raises.
- **Backend integration** (`test_osm_overpass_adapter.py`,
  `test_place_geometry.py`): `amenity_locations` caches + dedupes;
  `/amenities/geometry` returns merged multi-layer points (fake OSM client);
  `/children/geometry` returns 330 valued features for County Durham IMD and an
  empty collection for an LTLA-only indicator.
- **Frontend unit** (vitest): `colourDomain` pure-function tests (min/mid/max,
  nulls ignored); `renderAmenityMap` builds one circle layer + one legend
  swatch per amenity type.
- **Prompt test** (`test_ask_prompts.py`): assert three-mode guidance
  substrings (`granularity`, `sub_areas`, amenities overlay).
- **Schema test** (`test_ask_blocks.py`): a `map` block with `granularity` +
  `overlay.indicator_keys` validates; `overlay` with empty `indicator_keys` is
  rejected.

## Files touched (summary)

Backend:
- `server/soundings/adapters/osm_overpass/client.py` — `locations_by_tag`
- `server/soundings/adapters/osm_overpass/adapter.py` — `amenity_locations`
- `server/soundings/http/place_geometry.py` — `/children/geometry`,
  `/amenities/geometry`
- `server/soundings/ask/blocks.py` — `MapBlock.granularity`,
  `MapOverlay.indicator_keys`, narrowed `source`
- `server/soundings/ask/prompts.py` — map mode guidance

Frontend:
- `ui/src/lib/map-renderer.ts` — `colourDomain`, colour-scale fix, legends,
  `renderAmenityMap`
- `ui/src/scripts/ask_page.ts` — `renderMapBlock` rewrite

Tests: `test_osm_overpass_client.py`, `test_osm_overpass_adapter.py`,
`test_place_geometry.py` (new), `test_ask_prompts.py`, `test_ask_blocks.py`,
`ui/src/lib/__tests__/map-renderer.test.ts` (new or extended).

## Open questions / risks

- Public Overpass flakiness applies to location queries too. Mitigated by the
  raise-not-cache-zero behaviour and 30-day cache; a failed map overlay shows a
  block error, not a wrong map.
- Large urban areas may exceed the point cap; the cap + a "showing N of M"
  note keep payloads bounded. Acceptable for v1.
- Sub-area choropleth currently only has data for the deprivation family at
  LSOA. The prompt must steer `granularity: "sub_areas"` only to those
  indicators; the endpoint returning empty (→ peer fallback) is the safety net.

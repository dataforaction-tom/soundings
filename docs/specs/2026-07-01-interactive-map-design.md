# Interactive Map — Design Spec

**Date:** 2026-07-01
**Status:** Approved design — pending spec review, then implementation plan
**Parent:** Phase 6 (depth). Separate epic from the green-spaces loader bundle.

## Goal

Turn Soundings' maps from static, single-purpose renders into one **shared
interactive map component**, used both inline in ask answers and on a dedicated
**explorer page**. Deliver: clickable popups / side panel, combined point +
choropleth layers, switchable geography levels, and richer information.

## Current state (starting point)

- `ui/src/lib/map-renderer.ts` exposes stateless renderers: `renderPlaceMap`
  (boundary), `renderChoroplethMap` (peers or sub-areas; rank-coloured, no-data
  tolerant), `renderAmenityMap` (points) — mutually exclusive.
- Hover popups (name + value) + a legend. No click interaction, no layer mixing,
  no level switching.
- Geometry loaded for `lsoa21`, `ltla24`, `utla24`, `region` (NOT ward /
  constituency). Indicator data at LSOA exists only for `deprivation.*` and
  `environment.greenspace.*`; most other indicators are LTLA/UTLA.
- Endpoints: `/v1/place/{id}/geometry`, `/peers/geometry`, `/children/geometry`,
  `/amenities/geometry`. All are relative to one place.

## Architecture

### Shared component — `InteractiveMap`
New `ui/src/lib/interactive-map.ts`: a stateful class wrapping one MapLibre
instance. Responsibilities:
- Base tiles (existing tile URL plumbing).
- One **choropleth** layer (fill + outline), rank-coloured, no-data tolerant.
- N toggleable **point layers** (amenities), each colour-coded with a legend row.
- A **selection highlight** layer.
- Interaction hooks: `on('selectArea', cb)`, `on('selectPoint', cb)`, hover
  tooltip.

Public API (behaviour, not final signatures):
- `new InteractiveMap(container, { tilesUrl, mode })` — `mode: 'explorer' | 'inline'`.
- `setChoropleth({ indicatorKey, level, features, label })` — swaps the choropleth
  in place (no map teardown; zoom preserved).
- `addPointLayer(key, features, label)` / `removePointLayer(key)`.
- `setLevel(level)` — emits a request for new data (caller supplies features).
- `selectArea(placeId)` / `clearSelection()`.
- `destroy()`.

The existing pure helpers (`colourDomain`, `rankFractions`, `hasFiniteValues`,
`computeBounds`) move into or alongside the component unchanged. The current
`renderPlaceMap` / `renderChoroplethMap` / `renderAmenityMap` become thin wrappers
over `InteractiveMap` so existing callers (inline maps, place page) keep working
through the refactor.

### Explorer page — `ui/src/pages/explore.astro`
Layout: a control rail + the map + a side panel.
- **Controls:** indicator picker (choropleth-able indicators only); geography-level
  toggle (dynamic — see below); point-layer toggles (food banks, schools, GPs,
  parks); "load national neighbourhoods" action.
- **Map:** `InteractiveMap` in `explorer` mode.
- **Side panel:** shows the selected area's mini-profile.

### Inline answer maps
`ask_page.ts`'s map block mounts `InteractiveMap` in `inline` mode: choropleth
(+ optional amenity points when the block carries an overlay) with a **lightweight
click popup** (name + value + "View place →" link). No side panel.

## Backend

### New endpoint — national choropleth
`GET /v1/geographies/{type}/geometry?indicator=&period=`
Returns **all** areas of `{type}` coloured by an indicator: `{id, name, value,
percentile, geometry(simplified)}` per feature. Mirrors `peers/geometry`'s
value/percentile logic but is not relative to a place (no exclusion).
- Latest-period fallback via `COALESCE(:period, v.period)` (same fix as peers).
- **LSOA guard:** `type = lsoa21` (35k features) is served only when explicitly
  requested (the "load national neighbourhoods" action / an explicit query flag),
  to avoid accidental multi-MB payloads and slow renders.

### Reused endpoints
- **Drill-down** (LTLA → its LSOAs): existing `/children/geometry`.
- **Point layers**: existing `/amenities/geometry` (per focal area).
- **Side-panel mini-profile**: existing `get_place_profile` (a few headline
  indicators for one place).

## Geography levels + scale

- The level toggle offers only levels that have **both** geometry
  (`lsoa21`/`ltla24`/`utla24`/`region`) **and** data for the chosen indicator
  (from its `available_at`). Dynamic per indicator.
- Default view: **LTLA national**.
- LSOA reached two ways: **drill-down** (select an authority → load its LSOAs via
  `children/geometry`) or explicit **"load national neighbourhoods"** (enabled
  only for LSOA-capable indicators; hits the national endpoint with the LSOA
  guard opt-in).
- Ward / Westminster constituency: excluded (no boundaries loaded). Future work:
  load those boundary layers, then they become available levels automatically.

## Layers — points + choropleth together

- One choropleth underneath; multiple point layers on top, each toggleable and in
  the legend.
- Point layers load for the focal / selected area, never nationally (national
  amenity points would be enormous).

## Interaction

- **Explorer:** click area → highlight + side panel (mini-profile via
  `get_place_profile` + "View full profile →" link). Click point → small popup.
  Hover → light tooltip (name + active value).
- **Inline:** click area/point → lightweight popup (name + value + "View place →").

## Build sequence (each its own PR)

1. **National choropleth endpoint** (`/v1/geographies/{type}/geometry`) + integration
   tests (values, percentile, simplified geom, LSOA guard, latest-period fallback).
2. **Refactor renderers → `InteractiveMap`** (behaviour-preserving; inline + place
   maps switch to it; existing tests stay green) + inline click-through popups.
3. **Explorer page skeleton**: indicator picker + LTLA national choropleth +
   dynamic level toggle.
4. **Combined point-layer toggles**.
5. **Side panel mini-profile + selection**.
6. **LSOA drill-down + "load national neighbourhoods"**.

## Testing

- Pure logic in vitest: rank/colour helpers (done), level-availability resolver,
  point-layer state, popup content builders.
- Endpoint integration tests against the test DB.
- MapLibre WebGL rendering is not unit-testable in happy-dom → verified manually
  / e2e. Keep rendering logic thin and push decisions into tested pure functions.

## Out of scope

- Ward / constituency boundary loading (separate geometry task).
- National amenity-point layers.
- Time-slider / animating periods.

## Dependencies / sequencing

Builds on the map fixes already on `feat/green-spaces-loader` (peers period fix,
rank colouring, no-data handling, adapter registration). **Land the green-spaces
bundle first** (still needs OS Open Greenspace + Woodland), then start this epic
on its own branch.

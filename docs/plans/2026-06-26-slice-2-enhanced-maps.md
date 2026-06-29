# Slice 2: Enhanced Maps — Base Tiles + Point Overlay

**Goal:** Add OSM raster base tiles to maps, a configurable tile URL, and a point overlay layer for showing amenity/monitoring points on maps. Also pass tile config from server to client.

**Decisions (from plan):**
1. OSM raster tiles (`tile.openstreetmap.org`), configurable via `SOUNDINGS_MAP_TILES_URL`
2. MapBlock gets optional `overlay` field (for future: air quality monitors, amenities)

---

## Task breakdown

### Task 1: Add `SOUNDINGS_MAP_TILES_URL` env var + pass to client

**Files:**
- Modify: `ui/src/pages/ask.astro` — read env var, pass as data attribute on answer-surface
- Modify: `ui/src/pages/place/[id].astro` — same for place page map containers
- Modify: `ui/src/components/PlaceMap.astro` — read tile URL from data attribute
- Modify: `ui/src/components/ChoroplethMap.astro` — same
- Test: verify data attribute is present in SSR output

### Task 2: Add tile source to map-renderer.ts baseMapOptions

**Files:**
- Modify: `ui/src/lib/map-renderer.ts` — add optional `tilesUrl` param to `baseMapOptions()`, `renderPlaceMap()`, `renderChoroplethMap()`. When provided, add raster source + layer. When null/undefined, keep tile-less (backward compatible).
- Test: `ui/src/lib/__tests__/map-renderer.test.ts` — verify tile source added when URL provided, absent when not

### Task 3: Wire tile URL through ask_page.ts map renderer

**Files:**
- Modify: `ui/src/scripts/ask_page.ts` — pass tile URL from data attribute to renderPlaceMap/renderChoroplethMap calls

### Task 4: Add MapOverlay to block schema

**Files:**
- Modify: `server/soundings/ask/blocks.py` — add `MapOverlay` model and `overlay` field to `MapBlock`
- Test: `server/tests/test_ask_blocks.py` — verify overlay field defaults to None, valid when set

### Task 5: Update system prompt for overlay maps

**Files:**
- Modify: `server/soundings/ask/prompts.py` — mention overlay option in map block guidance
- Test: `server/tests/test_ask_prompts.py` — verify prompt mentions overlay

### Task 6: Full test suite + lint + type check

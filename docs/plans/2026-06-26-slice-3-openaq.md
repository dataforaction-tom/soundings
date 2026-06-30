# Slice 3: OpenAQ Air Quality Adapter

**Goal:** Add an OpenAQ passthrough adapter for air quality data (PM2.5, PM10, NO2, O3, SO2), catalogue entries, registry registration, and a tool for the ask interface.

**Source:** OpenAQ API v3 — `https://api.openaq.org/v3/`
- No auth required (API key optional for higher rate limits)
- `/v3/locations` — find monitoring stations by bounding box or coordinates
- `/v3/locations/{id}/sensors` — get sensors at a location
- `/v3/sensors/{sensor_id}/measurements` — get latest measurement value

**Methodology (decided):** IDW interpolation when multiple stations within 20km, nearest-station fallback if only one, null if none.

---

## Tasks

### Task 1: Add catalogue entries (sources.yaml + indicators.yaml)

**Files:**
- Modify: `catalogue/sources.yaml` — add `openaq` source entry
- Modify: `catalogue/indicators.yaml` — add 5 new indicators under `environment` domain
- Test: verify catalogue loads (existing test suite covers this)

### Task 2: Create OpenAQ client

**Files:**
- Create: `server/soundings/adapters/openaq/__init__.py`
- Create: `server/soundings/adapters/openaq/client.py` — async HTTP wrapper for OpenAQ v3 API
- Test: `server/tests/test_openaq_client.py`

### Task 3: Create OpenAQ adapter

**Files:**
- Create: `server/soundings/adapters/openaq/adapter.py` — PassthroughAdapter subclass
- Test: `server/tests/test_openaq_adapter.py`

### Task 4: Register adapter in app.py + add to system prompt

**Files:**
- Modify: `server/soundings/app.py` — register adapter
- Modify: `server/soundings/ask/prompts.py` — add environment domain
- Test: verify prompt mentions air quality

### Task 5: Full test suite + lint + type check

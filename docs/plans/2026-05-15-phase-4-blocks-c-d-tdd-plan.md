# Soundings v1 — Phase 4 Block C + Block D Implementation Plan (TDD)

> **For Claude:** TDD per task, commit per task. Branch `phase-4-block-c-ftc` first.
> Squash-merge into `main`, then `phase-4-block-d-find-orgs`.

## Current Phase 4 Status

- Block 0 ✅ merged — PassthroughAdapter extensions + pre_warmer scaffold
- Block A ✅ merged — Charity Commission loader + civil_society indicators
- Block B ✅ merged — 360Giving passthrough + grant indicators
- **Block C ⏳ NOT STARTED** — Find That Charity passthrough (Scotland/NI)
- **Block D ⏳ NOT STARTED** — find_organisations_in_place tool (orchestrator method)

---

## Block C — Find That Charity passthrough (Tasks 15–18)

### Task 15: `FindThatCharityClient`

**Files:**
- Create: `server/soundings/adapters/find_that_charity/__init__.py`
- Create: `server/soundings/adapters/find_that_charity/client.py`
- Create: `server/tests/test_ftc_client.py`

**TDD Pattern:**
1. Write `client.py` with the interface, implement `_call_upstream` returning mock data
2. Test fails → implement real client using `httpx.AsyncClient`
3. Test passes → commit

**API:** https://findthatcharity.uk/api/
- `get_charity(id: str)` — detail lookup by registered ID
- `search(name: str, postcode: str | None, country: str | None)` — cross-jurisdiction search

**Tests:**
- Mock transport tests: fake FTC responses, verify search params / detail fetch
- Client methods return typed dicts matching spec §4.6

**Commit:** `feat(adapters): find_that_charity async client`

---

### Task 16: `FindThatCharityAdapter`

**Files:**
- Create: `server/soundings/adapters/find_that_charity/adapter.py`
- Create: `server/tests/test_ftc_adapter.py`

**TDD Pattern:**
1. Write `adapter.py` stub with `fetch_organisations` returning empty list
2. Test `fetch_organisations` → fails with empty list assertion
3. Implement real `fetch_organisations` → routes based on place country:
   - Scotland → `country=Scotland`
   - NI → `country=Northern Ireland`
   - England/Wales → returns `[]` (E&W goes via CC loader)
4. Test passes → commit

**Key Points (per plan document):**
- `source_id = "find_that_charity"`, `mode = "passthrough"`
- Does NOT publish indicators (FTC count unreliable)
- Only implements `fetch_organisations`:
  ```python
  async def fetch_organisations(
      self,
      place_id: str,
      filters: list[str] | None = None,
      limit: int = 50,
  ) -> list[OrganisationRef]:
      # Resolve place country
      # If Scotland → search with country=Scotland
      # If NI → country=Northern Ireland
      # Else → return []
  ```

**Tests:**
- Mock client: returns sample charities for Scotland/Northern Ireland
- Assert E&W returns empty, Scotland returns list, NI returns list

**Commit:** `feat(adapters): FindThatCharityAdapter for cross-jurisdiction`

---

### Task 17: Register FTC + live test

**Files:**
- Modify: `server/soundings/app.py` (add to adapter registry)
- Create: `server/tests/live/test_ftc_live.py`

**TDD Pattern:**
1. Write live test expecting a known charity lookup (e.g., SC005336 Volunteer Scotland)
2. Test skips / fails → register adapter in app.py
3. Live test passes → commit

**Live Test:**
- Lookup SC005336 (Volunteer Scotland) resolves through adapter
- Uses `@pytest.mark.live`

**Commit:** `feat(app): register find_that_charity + ftc live smoke`

---

### Task 18: Block C docs

**Files:**
- Modify: `STATE.md` (mark Block C ✅)
- Modify: `PLAN.md`

**Commit:** `docs: block c — ftc cross-jurisdiction passthrough live`

**PR title:** `Phase 4 Block C: Find That Charity passthrough`

---

## Block D — `find_organisations_in_place` tool (Tasks 19–24)

### Task 19: Tool spec + Pydantic

**Files:**
- Create: `server/soundings/tools/find_organisations_in_place.py`
- Create: `server/tests/test_tool_find_organisations_spec.py`

**TDD Pattern:**
1. Write tool file with input/output schemas only
2. Test validates schema → fails → implement schemas
3. Test passes → commit

**Input Schema:**
```python
class FindOrganisationsInPlaceInput(BaseModel):
    place_id: str
    activity_filter: list[str] | None = None  # accepted but ignored in v1
    funded_only: bool = False  # if true, only orgs in data.grant_record
    limit: int = 50
```

**Output Schema:**
```python
class FindOrganisationsInPlaceOutput(BaseModel):
    organisations: list[OrganisationRef]
    sources: list[SourceRef]
    caveats: list[str] = []
    partial: bool = False
```

**Commit:** `feat(tools): find_organisations_in_place schema`

---

### Task 20: Orchestrator method

**Files:**
- Modify: `server/soundings/orchestration/orchestrator.py`
- Create: `server/tests/test_orchestrator_find_organisations.py`

**TDD Pattern:**
1. Write test: seeds cache + data.organisation for English LTLA + Scottish place
2. Test orchestrates → fails with orchestrator method not implemented
3. Implement method → pass

**Implementation (per plan document):**
```python
async def find_organisations_in_place(
    self,
    place_id: str,
    activity_filter: list[str] | None = None,
    funded_only: bool = False,
    limit: int = 50,
) -> FindOrganisationsResult:
    # 1. Resolve place country
    country = await self._resolve_place_country(place_id)

    # 2. Mixed-mode dispatch
    if country in ("England", "Wales"):
        # SELECT from data.organisation
        orgs = await self._orgs_from_loader(place_id, limit)
    elif country == "Scotland":
        # Route to FTC passthrough
        orgs = await self._orgs_via_ftc(place_id, limit)
    elif country == "Northern Ireland":
        # Route to FTC passthrough
        orgs = await self._orgs_via_ftc(place_id, limit)
    else:
        orgs = []

    # 3. funded_only: INNER JOIN to data.grant_record (empty in v1 → caveat)
    if funded_only:
        orgs = await self._filter_funded(orgs, place_id)

    # 4. Enrich with recent_grants from 360G (optional, cached)
    for org in orgs:
        org.recent_grants = await self._360g.recent_grants(place_id, limit=3)

    # 5. Return with deduped sources + caveats
    return FindOrganisationsResult(
        organisations=orgs,
        sources=dedup([...]),
        caveats=[...],
        partial=False,
    )
```

**Key Patterns:**
- E&W → SELECT from `data.organisation` where `registered_address_place_id = :pid`
- Scotland/NI → route to `find_that_charity.fetch_organisations` (passthrough)
- Enrich with `threesixtygiving.recent_grants(place_id, limit=3)`

**Tests:**
- Seed: `data.organisation` rows for English LTLA (loader path)
- Seed: cache with FTC payload for Scottish place (passthrough path)
- Assert right code path runs in each case + grants enrichment fires

**Commit:** `feat(orchestrator): find_organisations_in_place`

---

### Task 21: HTTP route

**Files:**
- Modify: `server/soundings/http/tools.py`
- Create: `server/tests/test_http_find_organisations.py`

**TDD Pattern:**
1. Write test: `POST /v1/tools/find_organisations_in_place` returns expected shape
2. Test fails → implement route
3. Test passes → commit

**Implementation:**
```python
@router.post("/v1/tools/find_organisations_in_place")
async def find_organisations_in_place_http(
    request: FindOrganisationsInPlaceInput,
    orchestrator: IndicatorOrchestrator = Depends(get_orchestrator),
) -> FindOrganisationsInPlaceOutput:
    result = await orchestrator.find_organisations_in_place(
        place_id=request.place_id,
        activity_filter=request.activity_filter,
        funded_only=request.funded_only,
        limit=request.limit,
    )
    return FindOrganisationsInPlaceOutput(
        organisations=result.organisations,
        sources=result.sources,
        caveats=result.caveats,
        partial=result.partial,
    )
```

**Commit:** `feat(http): POST /v1/tools/find_organisations_in_place`

---

### Task 22: MCP registration

**Files:**
- Modify: `server/soundings/mcp/server.py`

**TDD Pattern:**
1. Check MCP server for tool registration pattern (see existing tools)
2. Register `find_organisations_in_place` with same handler as HTTP
3. Commit

**Pattern:** Look at `find_place` / `get_indicators` MCP registration for reference.

**Commit:** `feat(mcp): register find_organisations_in_place tool`

---

### Task 23: e2e via both transports

**Files:**
- Create: `server/tests/test_phase_4_e2e_find_organisations.py`

**TDD Pattern:**
1. Seed cache.source_cache with CC + 360G payloads
2. Test: HTTP POST → assert response shape
3. Test: MCP call → assert same response
4. Commit

**Test:**
- Seeds cache for Stockton (E&W) + Scottish place
- Hits both transports
- Assert identical responses

**Commit:** `test: find_organisations_in_place e2e via HTTP + MCP`

---

### Task 24: Block D docs

**Files:**
- Modify: `STATE.md` (mark Block D ✅)
- Modify: `PLAN.md`

**Commit:** `docs: block d — find_organisations_in_place live on both transports`

**PR title:** `Phase 4 Block D: find_organisations_in_place tool`

---

## Block E — UI Surface (Tasks 25–27)

*(Optional if time permits, per original plan — otherwise defer to Phase 5)*

---

## Verification Checklist

After Block D lands, verify all simultaneously:

- [ ] `POST /v1/tools/find_organisations_in_place` returns `OrganisationRef[]` for E&W (via CC) and Scotland/NI (via FTC)
- [ ] Three new adapters live: `charity_commission` (loader-mode), `threesixtygiving` + `find_that_charity` (passthrough)
- [ ] Mixed-mode dispatch works: E&W → `data.organisation`, Scotland/NI → FTC passthrough
- [ ] 360G grant enrichment fires for both paths
- [ ] HTTP + MCP transports return identical results

---

## Commit Summary (per task)

| Task | Commit message |
|------|----------------|
| 15 | `feat(adapters): find_that_charity async client` |
| 16 | `feat(adapters): FindThatCharityAdapter for cross-jurisdiction` |
| 17 | `feat(app): register find_that_charity + ftc live smoke` |
| 18 | `docs: block c — ftc cross-jurisdiction passthrough live` |
| 19 | `feat(tools): find_organisations_in_place schema` |
| 20 | `feat(orchestrator): find_organisations_in_place` |
| 21 | `feat(http): POST /v1/tools/find_organisations_in_place` |
| 22 | `feat(mcp): register find_organisations_in_place tool` |
| 23 | `test: find_organisations_in_place e2e via HTTP + MCP` |
| 24 | `docs: block d — find_organisations_in_place live on both transports` |

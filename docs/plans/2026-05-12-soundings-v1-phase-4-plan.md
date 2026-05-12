# Soundings v1 — Phase 4 Implementation Plan

> **For Claude:** Same TDD-per-task / commit-per-task discipline as
> Phases 0–3. Conventions, commit prefixes, exact file paths. Branch
> per block, squash-merge PRs into `main` (the Phase 3 workflow).

## Architectural principle (sets the shape of every block)

**API-first where the upstream API supports our access pattern.**
Phase 4 onwards, every new public data source ships as a
**passthrough adapter** by default — we hold a TTL'd cached response
in `cache.source_cache`, not a long-lived copy of the publisher's
register. The canonical source is the source. Our DB is the
geography spine plus the questions corpus, not a shadow of CC / 360G
/ etc.

**The documented carve-out: Charity Commission.** Endpoint probing
during Block A confirmed CC API v2 is detail-lookup only (`GET
/register/api/allcharitydetailsV2/{regNumber}/{subNumber}`). There is
no search-by-postcode, search-by-area, or list-with-filter endpoint.
CC's bulk register download IS the publisher's official discovery
surface — so for CC, "API-first" actually means "bulk download
first", refreshed at the same monthly cadence CC themselves publish
at. Same pattern as Phase 1's IMD loader: cron-scheduled bulk pull,
streamed parse, idempotent upsert. 360G + FTC remain passthrough.

Implications:

- **`data.organisation` is populated by the CC loader** at monthly
  cadence — that's where `find_organisations_in_place` reads from
  for E&W. Scotland/NI route to the FTC passthrough adapter live.
  `data.grant_record` stays empty in Phase 4 (360G is passthrough).
- **Aggregate indicators (`civil_society.active_charities_*`) are
  loader-aggregated** at the end of each CC pass into
  `data.indicator_value`. Same shape as MYE / Census. Grant
  aggregates (`grants_in_last_12m_*`) ride on 360G GrantNav's
  pagination `totalCount` field, cached.
- **Pre-warm + long TTL** is the workhorse for 360G's aggregates.
  Each passthrough adapter that publishes a slow-changing aggregate
  overrides `pre_warm_for_places(place_ids)`; the `pre_warmer`
  daemon (Block 0) runs it on a cron so user-facing calls hit warm
  cache. CC doesn't need pre-warming — its values come from
  `data.indicator_value` already.
- **Carve-out criteria** for future bulk exceptions: (a) the
  publisher's API offers no discovery surface for the access pattern
  we need, AND (b) the data is structurally slow-changing (monthly+
  cadence). Anything not meeting both is passthrough by default.

This back-applies as a principle to Phase 5+ but does **not** mean
ripping out Phase 1's MYE / Census / IMD loaders — those work, they
ship value, and they predate this principle. Future indicators on
those sources can be passthrough; the existing loaders stay.

---

**Goal:** Civil-society context. Soundings answers "what organisations
work in this place?" and "what grants flowed into this place last
year?" alongside the existing population / economy / deprivation
answers. Phase 4 ends when:

1. Tool `find_organisations_in_place` is live on HTTP + MCP.
2. The four catalogue `civil_society.*` indicators already declared in
   `catalogue/indicators.yaml` resolve to real values via
   `get_indicators` / `get_place_profile`. Charity counts come from
   `data.indicator_value` (CC loader writes); grant aggregates come
   from cached 360G GrantNav queries (passthrough).
3. Three new adapters wired through `AdapterRegistry`:
   `charity_commission` (loader-mode, monthly bulk), `threesixtygiving`
   (passthrough), `find_that_charity` (passthrough).
4. The `pre_warmer` daemon (Block 0) covers 360G's grant aggregates.
   CC values don't need pre-warming — they live in `data.indicator_value`.
5. `/place/[id]` shows an "Organisations" section with the top N
   active charities + a "Recent grants in" summary.
6. Live tests for all three new adapters run nightly.
7. Tag `v0.5.0-phase-4` pushed once browser smoke + live tests are
   green.

**Architecture:** Per `docs/plans/2026-05-05-soundings-v1-design.md` §3
(`PassthroughAdapter` base class) and §4.6 (tool shape). Extends
`PassthroughAdapter` with two optional methods:

- `fetch_organisations(place_id, filters)` — returns `list[OrganisationRef]`.
- `pre_warm_for_places(place_ids)` — best-effort cache warmer.

Both default to no-op so existing adapters (Fingertips, Stat-Xplore,
DfE, APS, police.uk) inherit them without change.

**Tech stack additions on top of Phase 3:**

| Dep | Purpose | Asked? |
|---|---|---|
| (no new Python deps) | All adapters reuse `httpx` + `aiolimiter` + the existing `PassthroughAdapter` base | n/a |
| (no new JS deps) | UI re-uses the existing `IndicatorCard` / `SourceCitations` shapes for the Organisations section | n/a |
| Second supervisor process (`pre_warmer`) | Same image as `loader`, different command — `python -m soundings.pre_warmer.run` | New process, no new image |

**Estimated scope:** ~29 tasks across 6 blocks. ~1 focused week per
spec §13. Blocks A, B, C can parallelise after Block 0's contract
extensions land (Block 0 already shipped in PR #7).

---

## Prerequisites Tom needs to do before Block A

- **Already done — pre_warmer service added in Block 0.** Compose
  service exists, no new infra needed for Block A.
- **No registration required for Block A.** The CC bulk register
  download is anonymous (no API key). `CHARITY_COMMISSION_API_KEY` is
  in `.env` already but isn't used by the Phase 4 CC loader — it stays
  reserved for future per-charity detail enrichment work.
- **No registration for 360Giving GrantNav.** Public.
- **No registration for Find That Charity.** Public.

---

## Architectural decisions

These are the calls baked into the plan. Push back on any of them
before Block A starts.

| Decision | Rationale |
|---|---|
| **CC is loader-mode (monthly bulk pull); 360G + FTC stay passthrough.** | API-first wherever the upstream API supports our access pattern. Endpoint probing during pre-Block-A confirmed CC API v2 is detail-lookup-by-regNumber only — no search-by-area / search-by-postcode / list-with-filter. CC's official discovery surface IS the monthly bulk register download. Same pattern + cron-driven loader as Phase 1's IMD. 360G GrantNav has a real search API; FTC has detail + reconcile endpoints — both stay passthrough. |
| **The bulk-download carve-out is permitted when:** (a) the publisher's API offers no discovery surface for our access pattern AND (b) the data is structurally slow-changing (monthly+ cadence). | Any future bulk exception needs both conditions documented in its plan. Most upstream sources will continue as passthrough by default. |
| **`PassthroughAdapter` grows two optional methods** (`fetch_organisations`, `pre_warm_for_places`). | Already shipped in Block 0. Avoids a parallel base class. Existing adapters inherit no-op defaults. Orchestrator's `find_organisations_in_place` fans out across adapters that override `fetch_organisations` PLUS reads `data.organisation` for loader-mode sources like CC. |
| **`pre_warmer` Docker Compose service runs the cache-warming cron.** | Already shipped in Block 0. Covers 360G aggregates in Block B. CC values land in `data.indicator_value` via the loader, no warming needed. |
| **`data.organisation` is populated by the CC loader; `data.grant_record` stays empty.** | CC's only structural reason for bulk; 360G is passthrough so no grant rows. The Phase 3-era empty-table state holds for `data.grant_record` through Phase 4; v2 enrichment work can revisit. |
| **Aggregate indicators are computed at the canonical place for each mode.** | Loader-mode CC: `civil_society.active_charities_*` aggregated at end of loader pass into `data.indicator_value`, same shape as MYE. Passthrough 360G: `civil_society.grants_in_last_12m_*` ride on GrantNav pagination `totalCount`, cached at LTLA granularity. |
| **`find_organisations_in_place` fans out across mixed-mode sources per call.** | E&W places: SELECT from `data.organisation` for the CC slice (cheap), optionally enrich via 360G passthrough for `recent_grants`. Scotland / NI: route to `find_that_charity` passthrough. Each fan-out leg has the same 10s soft budget as the existing orchestrator. |
| **Activity filter is accepted but ignored in v1.** | CC publishes activity codes that aren't ICNPO; mapping is judgement-heavy and lands in v2. API shape stays stable so v2 doesn't force a tool-spec change. |
| **Phase 4 PR workflow matches Phase 3.** | One feature branch per block, squash-merged PRs into `main`. No direct commits to `main`. |

---

## Open questions

Push back if any default is wrong.

1. **CC loader cron pattern.** Plan default: monthly on the 18th at
   04:00 UTC (`0 4 18 * *`) — CC publishes mid-month, so the 18th
   gives a few days' buffer.
2. **360G pre-warmer cadence.** Plan default: weekly for grant
   aggregates. ~330 LTLAs × one GrantNav query / week = polite.
3. **Should `find_organisations_in_place` cap on the number of
   fan-outs?** Plan default: yes — primary adapter (CC loader-SQL
   for E&W, FTC passthrough for Scotland/NI) plus optional 360G
   grant enrichment. At most 2 upstreams hit per call.
4. **`grants_in_last_12m_*` semantics — beneficiary-based or
   recipient-address-based?** Plan default: beneficiary
   (`recipientLocations` in 360G's payload). Coverage gap caveat —
   many records lack beneficiary postcode; the figure undercounts.

---

## Conventions used in this plan

- **TDD throughout.** Every behaviour task: failing test → minimum
  implementation → green → commit.
- **Commits per task** with conventional-commits prefixes (`feat`,
  `chore`, `test`, `refactor`, `docs`, `ci`).
- **Exact file paths** relative to repo root unless prefixed `/`.
- **Live tests** for every new adapter under `server/tests/live/`.
  Mock-transport tests for non-live PR-time coverage.
- **One PR per block**, squash-merged. Block branch names like
  `phase-4-block-a-cc`.

---

## Block 0 — Adapter base + contracts (Tasks 1–3)

### Task 1: Extend `PassthroughAdapter` with `fetch_organisations` + `pre_warm_for_places`

**Files:**
- Modify: `server/soundings/adapters/passthrough_base.py`
- Modify: `server/tests/test_passthrough_base.py` (or create if missing)

Both methods are optional with no-op defaults. `fetch_organisations`
returns `list[OrganisationRef]`. `pre_warm_for_places` returns
nothing; failures are swallowed and logged.

Commit: `feat(adapters): PassthroughAdapter — fetch_organisations + pre_warm`.

### Task 2: `OrganisationRef` + `GrantRef` Pydantic contracts

**Files:**
- Create: `server/soundings/contracts/organisation.py`
- Create: `server/tests/test_organisation_contracts.py`

Mirror design §4.6. `OrganisationRef` carries id / name /
classification / `registered_address_place_id` / `operates_in_place_ids`
/ `recent_grants` / `source` (a SourceRef). `GrantRef` is funder /
amount / currency / date / purpose / source.

Commit: `feat(contracts): OrganisationRef + GrantRef pydantic models`.

### Task 3: `pre_warmer` daemon scaffold

**Files:**
- Create: `server/soundings/pre_warmer/__init__.py`
- Create: `server/soundings/pre_warmer/run.py`
- Modify: `infra/docker-compose.yml`
- Modify: `infra/Dockerfile.server` (no change expected — same image)
- Create: `server/tests/test_pre_warmer_scaffold.py`

APScheduler instance, modelled after `loader/run.py`. Reads
registered adapters from `AdapterRegistry`, invokes
`pre_warm_for_places(ltlas)` on each that overrides it. Cron pattern
read from `sources.yaml` per source.

Compose service:

```yaml
pre_warmer:
  image: soundings-server
  command: ["python", "-m", "soundings.pre_warmer.run"]
  depends_on: { postgres: { condition: service_healthy } }
  restart: unless-stopped
```

Commit: `feat(infra): pre_warmer daemon for passthrough aggregate caches`.

PR title: `Phase 4 Block 0: passthrough base + pre_warmer scaffold`.

---

## Block A — Charity Commission loader (Tasks 4–10)

> Loader-mode by exception per the architectural-decisions table above:
> CC API v2 is detail-lookup only with no search-by-area endpoint, and
> the data is monthly-cadence — bulk download is the publisher's
> official discovery surface. Same shape as Phase 1's IMD loader.

### Task 4: `CharityCommissionBulkClient`

**Files:**
- Create: `server/soundings/adapters/charity_commission/__init__.py`
- Create: `server/soundings/adapters/charity_commission/client.py`
- Create: `server/tests/test_cc_client.py`

Downloads the latest bulk register ZIP from
<https://register-of-charities.charitycommission.gov.uk/register/full-register-download>
and streams the CSVs out without keeping the full archive in memory.

The register publishes ~6 CSVs; we need at minimum `charity` (the
core entity table) + `charity_main_charity` (active flag + contact
details). The client exposes `iter_active_charities()` yielding dicts
with the merged columns we care about: `registration_number`, `name`,
`postcode`, `status`, `activities_text`, `cc_classification`.

`httpx.MockTransport` test seeds a fake ZIP via `zipfile.ZipFile` over
`io.BytesIO`; asserts the iterator yields the expected merged rows.

Anonymous — no API key. (`CHARITY_COMMISSION_API_KEY` stays reserved
for future per-charity detail enrichment work; Phase 4 doesn't use it.)

Commit: `feat(adapters): charity commission bulk register client`.

### Task 5: Postcode batch resolver

**Files:**
- Create: `server/soundings/adapters/charity_commission/mapping.py`
- Create: `server/tests/test_cc_mapping.py`

`resolve_postcodes_to_places(postcodes_io_client, postcodes)` batches
100 postcodes per `postcodes.io` POST request, returns
`dict[postcode, place_id]` indexed by LTLA (`ltla24:E...`). Unknown
postcodes return None and get counted in `notes`, not hard-error.
Caches in `geography.postcode` on the way through so re-runs only
look up novel postcodes (idempotent).

Commit: `feat(adapters): cc postcode batch resolution via postcodes.io`.

### Task 6: `CharityCommissionLoader` — write to `data.organisation`

**Files:**
- Create: `server/soundings/adapters/charity_commission/loader.py`
- Create: `server/tests/test_cc_loader.py`

`source_id = "charity_commission"`, `mode = "loader"`. `load()`:

1. Stream every "active" row from `CharityCommissionBulkClient.iter_active_charities`.
2. Batch-resolve postcodes via the Task 5 helper.
3. Upsert into `data.organisation`:
   - `id` = `"charity_commission:NNNNNN"` (CC reg number)
   - `name` = charity name
   - `classification` = ARRAY from CC activity codes
   - `registered_address_place_id` = resolved LTLA (nullable)
   - `source_id` = `charity_commission`
   - `raw` = the full merged row as JSONB
4. Also upsert a row into `data.organisation_operates_in` linking the
   org to its registered LTLA — v1 "operates in" approximation.

`on_conflict_do_update` so re-runs refresh `retrieved_at`. Removed /
dissolved charities flagged via `raw->>'status'` rather than being
deleted — keeps history for v2 enrichment without polluting the
active aggregate.

Integration test (mock client + real DB) seeds 10 charities across 3
LTLAs, runs the loader, asserts row counts and that
`organisation_operates_in` is symmetric with
`registered_address_place_id`.

Commit: `feat(adapters): CharityCommissionLoader populates data.organisation`.

### Task 7: CC indicator aggregation — `civil_society.active_charities_*`

**Files:**
- Modify: `server/soundings/adapters/charity_commission/loader.py`
- Create: `server/tests/test_cc_indicator_aggregation.py`

End of `load()`, two aggregating UPSERTs to `data.indicator_value`:

- `civil_society.active_charities_count` — count per `place_id` of
  organisations where `source_id='charity_commission'` and
  `raw->>'status' = 'Active'`.
- `civil_society.active_charities_per_10k` — same count divided by
  the latest `population.total` for that place × 10_000. Reads
  population from the existing `data.indicator_value` row; skips
  places without population (logged in `loader_run.notes`).

Both rows stamped with the current `loader_run_id` so `cache_status`
flows from the existing `LoaderAdapter.fetch_indicator` plumbing.

Commit: `feat(adapters): CC loader emits civil_society indicator aggregates`.

### Task 8: Register CC adapter

**Files:**
- Modify: `server/soundings/adapters/charity_commission/__init__.py`
- Modify: `server/soundings/app.py` (`build_adapter_registry`)
- Modify: `server/soundings/loader/run.py` (add to source registry)

Re-export `CharityCommissionLoader` under the canonical
`CharityCommissionAdapter` name (matches the MYE / IMD pattern), wire
into `build_adapter_registry`. The loader daemon picks up the
`sources.yaml` `refresh_cadence` already pinned for
`charity_commission`.

Commit: `feat(app): register charity_commission + civil_society aggregates`.

### Task 9: Live test for the CC loader

**Files:**
- Create: `server/tests/live/test_cc_live.py`

Marker `live` + `integration`. Downloads the real bulk register
(rate-limited — once per nightly run) and asserts:

- ≥100_000 active charities seed without error.
- At least one charity resolves to `ltla24:E06000004` (Stockton).
- `data.indicator_value` has `civil_society.active_charities_count`
  for at least 5 distinct LTLAs.

A timeout caveat: if CC's bulk download is >60s slow, mark the test
`xfail` rather than failing nightly — upstream flakiness shouldn't
blank our CI. Also pipe `STATXPLORE_API_KEY` through nightly.yml at
the same time (it's currently in the workflow's expected secrets but
not the env block — see Phase 3 follow-up).

Commit: `test: cc live smoke + civil_society aggregation`.

### Task 10: Block A docs

**Files:**
- Modify: `STATE.md`
- Modify: `PLAN.md`
- Modify: `.env.example` (fix the `DWP_STATXPLORE_KEY` → `STATXPLORE_API_KEY` name mismatch)

Commit: `docs: block a — cc loader shipped, aggregation flowing`.

PR title: `Phase 4 Block A: Charity Commission loader + civil_society indicators`.

---

## Block B — 360Giving passthrough (Tasks 11–15)

### Task 10: `ThreeSixtyGivingClient`

**Files:**
- Create: `server/soundings/adapters/threesixtygiving/__init__.py`
- Create: `server/soundings/adapters/threesixtygiving/client.py`
- Create: `server/tests/test_360g_client.py`

Pull from <https://grantnav.threesixtygiving.org/api/>. Methods:

- `search_grants(filters: dict, page: int, page_size: int)` —
  paginated grants. Filters include `recipientPostcode` /
  `recipientRegionName` / `awardDate` ranges.
- `aggregate_grants(filters: dict)` — uses the API's facet aggregator
  if it exposes one; else falls back to a count-only single-page
  search and reads `totalReturned`. Sum requires either a facet sum
  or a small in-process aggregation across all pages (acceptable
  because Phase 4 sums for one LTLA = O(hundreds of grants), not
  millions).

Commit: `feat(adapters): 360Giving grantnav async client`.

### Task 11: `ThreeSixtyGivingAdapter` (passthrough)

**Files:**
- Create: `server/soundings/adapters/threesixtygiving/adapter.py`
- Create: `server/tests/test_360g_adapter.py`

`source_id = "threesixtygiving"`, `mode = "passthrough"`,
`ttl=timedelta(days=7)`.

- `fetch_indicator(civil_society.grants_in_last_12m_total, place_id)`
  → query GrantNav with beneficiary place filter + date window, sum
  amounts, return as IndicatorValue.
- `fetch_indicator(civil_society.grants_in_last_12m_count, place_id)`
  → same query, count from `totalReturned`.
- `fetch_organisations` — not implemented (360G isn't a register).
- `recent_grants(place_id, limit)` — query GrantNav for recent
  grants involving `place_id`, used by Block D's tool to enrich the
  `recent_grants` field on an `OrganisationRef`.

Commit: `feat(adapters): ThreeSixtyGivingAdapter passthrough + recent_grants`.

### Task 12: 360G pre-warmer

**Files:**
- Modify: `server/soundings/adapters/threesixtygiving/adapter.py`
- Create: `server/tests/test_360g_pre_warm.py`

Pre-warm the two indicators for every LTLA. Weekly cadence
(grants_in_last_12m moves slowly).

Commit: `feat(adapters): 360G pre_warm_for_places(ltlas) for grant cache`.

### Task 13: Register 360G + live test

**Files:**
- Modify: `server/soundings/app.py`
- Create: `server/tests/live/test_360g_live.py`

Live test confirms `recent_grants("ltla24:E06000004", limit=5)`
returns ≥1 grant with a non-zero amount.

Commit: `feat(app): register threesixtygiving + 360G live smoke`.

### Task 14: Block B docs

**Files:**
- Modify: `STATE.md`
- Modify: `PLAN.md`

Commit: `docs: block b — 360G passthrough live`.

PR title: `Phase 4 Block B: 360Giving passthrough + grant indicators`.

---

## Block C — Find That Charity passthrough (Tasks 16–19)

### Task 15: `FindThatCharityClient`

**Files:**
- Create: `server/soundings/adapters/find_that_charity/__init__.py`
- Create: `server/soundings/adapters/find_that_charity/client.py`
- Create: `server/tests/test_ftc_client.py`

FTC JSON API at <https://findthatcharity.uk/api/>. Methods:

- `get_charity(id: str)` — by registered ID (cross-regulator)
- `search(name: str, postcode: str | None, country: str | None)` —
  cross-jurisdiction search.

Commit: `feat(adapters): find_that_charity async client`.

### Task 16: `FindThatCharityAdapter`

**Files:**
- Create: `server/soundings/adapters/find_that_charity/adapter.py`
- Create: `server/tests/test_ftc_adapter.py`

`source_id = "find_that_charity"`, `mode = "passthrough"`. Doesn't
publish indicators (count via FTC isn't reliable — it aggregates
multiple regulators). Implements `fetch_organisations` only:

- `fetch_organisations(place_id, filters, limit)` →
  - If `place_id` country is Scotland → search with `country=Scotland`
  - If Northern Ireland → `country=Northern Ireland`
  - Else → return [] (E&W goes via CC)

Commit: `feat(adapters): FindThatCharityAdapter for cross-jurisdiction`.

### Task 17: Register FTC + live test

**Files:**
- Modify: `server/soundings/app.py`
- Create: `server/tests/live/test_ftc_live.py`

Live test: lookup known SC005336 (Volunteer Scotland) resolves
through the adapter.

Commit: `feat(app): register find_that_charity + ftc live smoke`.

### Task 18: Block C docs

**Files:**
- Modify: `STATE.md`
- Modify: `PLAN.md`

Commit: `docs: block c — ftc cross-jurisdiction passthrough live`.

PR title: `Phase 4 Block C: Find That Charity passthrough`.

---

## Block D — `find_organisations_in_place` tool (Tasks 20–25)

### Task 19: Tool spec + Pydantic

**Files:**
- Create: `server/soundings/tools/find_organisations_in_place.py`
- Create: `server/tests/test_tool_find_organisations_spec.py`

`FindOrganisationsInPlaceInput` (place_id, activity_filter,
funded_only, limit) + `Output` (organisations: list[OrganisationRef],
sources, caveats, partial). Schema-only.

Commit: `feat(tools): find_organisations_in_place schema`.

### Task 20: Orchestrator method

**Files:**
- Modify: `server/soundings/orchestration/orchestrator.py`
- Create: `server/tests/test_orchestrator_find_organisations.py`

`find_organisations_in_place(place_id, activity_filter, funded_only,
limit)`:

1. Resolve `geography.place(id)` → fetch `country` + `type`.
2. **Mixed-mode dispatch**:
   - England / Wales → SELECT from `data.organisation` where
     `registered_address_place_id = :pid` OR `id IN (SELECT
     organisation_id FROM data.organisation_operates_in WHERE
     place_id = :pid)`. Loader-mode CC populates this on a monthly
     cron — `data.organisation` is the canonical surface for E&W.
   - Scotland / NI → call `find_that_charity.fetch_organisations`
     (passthrough, FTC adapter overrides the method per Block C).
3. If `funded_only=true`, INNER JOIN to `data.grant_record` on
   `recipient_org_id` (table is empty in Phase 4, so this returns []
   until v2 — caveated in the response).
4. Optionally enrich each result with
   `threesixtygiving.recent_grants(place_id, limit=3)` so the
   `recent_grants` field on `OrganisationRef` carries up to three
   GBP grants — 360G is passthrough, cached.
5. Return list + dedup-ed SourceRefs + any caveats from the
   adapters. `partial=True` if any leg errors out.

Test seeds catalogue + `data.organisation` rows for an English LTLA
(loader path) + cache.source_cache with an FTC payload for a Scottish
place (passthrough path); asserts the right code path runs in each
case + the grants enrichment fires.

Commit: `feat(orchestrator): find_organisations_in_place`.

### Task 21: HTTP route

**Files:**
- Modify: `server/soundings/http/tools.py`
- Create: `server/tests/test_http_find_organisations.py`

`POST /v1/tools/find_organisations_in_place`.

Commit: `feat(http): POST /v1/tools/find_organisations_in_place`.

### Task 22: MCP registration

**Files:**
- Modify: `server/soundings/mcp/server.py`

Add tool registration. Same handler.

Commit: `feat(mcp): register find_organisations_in_place tool`.

### Task 23: e2e via both transports

**Files:**
- Create: `server/tests/test_phase_4_e2e_find_organisations.py`

Seeds cache.source_cache with CC + 360G payloads for an LTLA, hits
both transports, asserts identical responses.

Commit: `test: find_organisations_in_place e2e via HTTP + MCP`.

### Task 24: Block D docs

**Files:**
- Modify: `STATE.md`
- Modify: `PLAN.md`

Commit: `docs: block d — find_organisations_in_place live on both transports`.

PR title: `Phase 4 Block D: find_organisations_in_place tool`.

---

## Block E — UI surface for organisations (Tasks 26–28)

### Task 25: `lib/api.ts` wrapper + types

**Files:**
- Modify: `ui/src/lib/api.ts`
- Modify: `ui/src/lib/types.ts`
- Modify: `ui/tests/api.test.ts`

`findOrganisationsInPlace(placeId, opts)`. TS mirrors of
`OrganisationRef` / `GrantRef`.

Commit: `feat(ui): typed wrapper for find_organisations_in_place`.

### Task 26: Components + `/place/[id]` integration

**Files:**
- Create: `ui/src/components/OrganisationsSection.astro`
- Create: `ui/src/components/OrganisationCard.astro`
- Modify: `ui/src/pages/place/[id].astro`
- Create: `ui/tests/organisation_card.test.ts`

Section renders below the existing Indicators / Sources panels.
Cards: charity name, registered LTLA, classification tags, top-3
recent grants inline. SSR fetch fans out alongside the existing
trend fan-out. If the place isn't E&W and FTC returns nothing,
section silently no-ops.

Commit: `feat(ui): /place/[id] shows organisations + recent grants`.

### Task 27: `/about` mentions civil-society context

**Files:**
- Modify: `ui/src/pages/about.astro`

Two sentences explaining the section + upstream sources.

Commit: `docs(ui): /about mentions civil society context`.

PR title: `Phase 4 Block E: UI surface for organisations`.

---

## Block F — Integration, e2e, tag (Tasks 29–32)

### Task 28: Phase 4 e2e — server-side

**Files:**
- Create: `server/tests/test_phase_4_e2e.py`

Cache-seeds CC + 360G responses for Stockton + an SOA in Scotland.
POSTs `find_organisations_in_place` for both; asserts the right
adapter served each leg and the response shape's right.

Commit: `test: phase 4 e2e — find_organisations across CC + FTC`.

### Task 29: Browser smoke runbook

**Files:**
- Create: `docs/runbook-phase-4-smoke.md`

Like the Phase 3 runbook. Notes:
- `make seed-light` now also runs the CC loader (`--once
  charity_commission`) — this is the heavy one (~5 min, ~50MB
  download). For dev iteration, document a place-filtered subset
  pull so seeding stays under 1 min.
- For 360G aggregates: `python -m soundings.pre_warmer.run --once
  threesixtygiving` warms the grant-sum cache for the seeded LTLAs.

Commit: `docs(runbook): phase 4 browser smoke`.

### Task 30: Update STATE.md + PLAN.md

**Files:**
- Modify: `STATE.md`
- Modify: `PLAN.md`

Mark Phase 4 complete, list Phase 5 follow-ups.

Commit: `docs: phase 4 complete — CC loader + 360G/FTC passthrough + find_organisations`.

### Task 31: Tag `v0.5.0-phase-4`

**Steps:**

1. `make lint && make type && make test && make test-integration`.
2. `make up && make migrate && make seed-light`.
3. Pre-warm CC cache for the seeded LTLAs.
4. Browser smoke per Task 29 runbook.
5. Tag + push.

PR title for Block F: `Phase 4 Block F: integration + tag prep`.

---

## Done criteria for Phase 4

All green simultaneously:

- [ ] `POST /v1/tools/find_organisations_in_place` returns
      `OrganisationRef[]` for E&W (via CC) and Scotland/NI (via FTC).
- [ ] `civil_society.active_charities_count`,
      `civil_society.active_charities_per_10k`,
      `civil_society.grants_in_last_12m_total`, and
      `civil_society.grants_in_last_12m_count` resolve to real values
      for at least the LTLAs covered by `make seed-light`.
- [ ] Three new adapters live: `charity_commission` (loader-mode,
      monthly bulk pull), `threesixtygiving` + `find_that_charity`
      (passthrough).
- [ ] `pre_warmer` service running in compose, warming the 360G grant
      aggregate cache on a weekly cron. CC counts come from the
      loader's `data.indicator_value` writes, no warming needed.
- [ ] `data.organisation` populated by the CC loader (~220k rows after
      `make seed`). `data.grant_record` stays empty in Phase 4
      (passthrough 360G doesn't write to it; v2 enrichment will).
- [ ] `/place/[id]` renders an Organisations section for E&W places
      and degrades cleanly elsewhere.
- [ ] Nightly live tests for all three new adapters green.
- [ ] `STATE.md` + `PLAN.md` updated, `v0.5.0-phase-4` tagged.

## Out of scope

- Phase 5+ work — separate plan documents.
- `data.grant_record` population — v2 enrichment (360G stays
  passthrough in Phase 4; v2 might mirror grant detail for richer
  joins).
- ICNPO ↔ CC activity-code mapping — v2 task.
- Operational-reach geography (`operates_in` beyond registered
  address) — v2 task using FTC's geo joins.
- Per-charity CC API enrichment (`allcharitydetailsV2/{regNumber}`)
  for richer detail beyond what the bulk register provides —
  `CHARITY_COMMISSION_API_KEY` is parked for this future work.
- Backfilling earlier Phase 1 loaders (MYE / Census / IMD) to
  passthrough — the API-first principle applies forward only; the
  existing loaders ship value and stay.
- Daily CC delta sync via the `recentchanges` endpoint (option 2b
  from the design discussion). Monthly cadence matches CC's
  publishing cadence; near-real-time freshness isn't worth the extra
  cron job for v1.

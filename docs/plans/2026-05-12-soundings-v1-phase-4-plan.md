# Soundings v1 — Phase 4 Implementation Plan

> **For Claude:** Same TDD-per-task / commit-per-task discipline as
> Phases 0–3. Conventions, commit prefixes, exact file paths. Branch
> per block, squash-merge PRs into `main` (the Phase 3 workflow).

## Architectural principle (sets the shape of every block)

**API-first. Cache, don't mirror.** Phase 4 onwards, every new public
data source ships as a **passthrough adapter** — we hold a cached
response in `cache.source_cache`, not a long-lived copy of the
publisher's register. The canonical source is the source. Our DB is
the geography spine plus the questions corpus, not a shadow of CC /
360G / etc.

Implications:

- **No `data.organisation` / `data.grant_record` writes in Phase 4.**
  Those tables stay in the schema as v2 enrichment destinations
  (org self-registration, contributed observations) but Phase 4
  doesn't populate them.
- **Aggregate indicators that need full-register traversal** (like
  `civil_society.active_charities_count`) ride on upstream pagination
  metadata where available (`totalCount` / `totalReturned` fields).
  Where the upstream doesn't expose a cheap count, the adapter logs
  the gap in `caveats` rather than paging through 220k rows on every
  call.
- **Pre-warm + long TTL** is the workhorse for aggregates. Each
  passthrough adapter that publishes a slow-changing aggregate
  exposes an optional `pre_warm_for_places(place_ids)` method; a
  separate `pre_warmer` daemon (split from the existing `loader`
  daemon) runs it on a cron so user-facing calls almost always hit a
  warm cache. TTLs match `sources.yaml` `refresh_cadence`.
- **No raw 50MB CSV / XLSX downloads in Phase 4.** The CC bulk
  register, 360G data dumps, etc. are NOT touched. Live API only.

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
   `get_indicators` / `get_place_profile`, served from live CC + 360G
   API calls (cached).
3. Three new passthrough adapters wired through `AdapterRegistry`:
   `charity_commission`, `threesixtygiving`, `find_that_charity`.
4. A `pre_warmer` daemon runs on a cron, pre-populating the cache for
   the E&W LTLA universe so user-facing reads hit warm cache.
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

**Estimated scope:** ~28 tasks across 6 blocks. ~1 focused week per
spec §13 (shorter than the loader-flavoured original draft because
there are no bulk download / postcode-resolution paths to build).
Blocks A, B, C can parallelise after Block 0's contract extensions
land.

---

## Prerequisites Tom needs to do before Block A

- **Register for a Charity Commission API subscription key** at
  <https://api.charitycommission.gov.uk/> — free, instant.
  Store as `CHARITY_COMMISSION_API_KEY` in `soundings-ops` and add
  to GitHub Actions Secrets. The public bulk download is anonymous;
  the per-query API isn't.
- **No registration for 360Giving GrantNav.** Public.
- **No registration for Find That Charity.** Public.
- **Confirm the pre-warmer fits the current Docker Compose budget.** A
  new `pre_warmer` service is ~the same shape as `loader` — minimal
  cost, but Tom should agree before we add it.

---

## Architectural decisions

These are the calls baked into the plan. Push back on any of them
before Block A starts.

| Decision | Rationale |
|---|---|
| **Every Phase 4 adapter is passthrough.** | API-first per the section above. CC API + 360G API + FTC API all support per-place queries; we don't need to mirror their registers. |
| **`PassthroughAdapter` grows two optional methods** (`fetch_organisations`, `pre_warm_for_places`). | Avoids a parallel base class. Existing adapters inherit no-op defaults. Orchestrator's `find_organisations_in_place` fans out across adapters that override `fetch_organisations`. |
| **A new `pre_warmer` Docker Compose service runs the cache-warming cron.** | Keeps user-facing latency low for aggregate indicators. Same image as `loader`, different entrypoint. Schedule is conservative — daily for orgs, weekly for grants. |
| **Aggregate indicators use upstream `totalCount` / `totalReturned` fields where they exist.** | One API call, one number cached. CC's search API and 360G GrantNav both return totals in their pagination envelope. If a future upstream doesn't, the adapter falls back to a paged sample + extrapolation with a caveat. |
| **No writes to `data.organisation` or `data.grant_record` in Phase 4.** | Those tables stay as v2 enrichment destinations. Removing them now would churn the migration history for no near-term gain. |
| **`find_organisations_in_place` fans out across multiple passthrough adapters per call.** | E&W places query `charity_commission`; Scotland / NI route to `find_that_charity`; the response merges. Grant enrichment optionally calls `threesixtygiving` for the same place. Each fan-out leg has the same 10s soft budget as the existing orchestrator. |
| **Activity filter is accepted but ignored in v1.** | CC publishes activity codes that aren't ICNPO; mapping is judgement-heavy and lands in v2. API shape stays stable so v2 doesn't force a tool-spec change. |
| **Phase 4 PR workflow matches Phase 3.** | One feature branch per block, squash-merged PRs into `main`. No direct commits to `main`. |

---

## Open questions

Push back if any default is wrong.

1. **What's the right pre-warmer cadence?** Plan default: daily for
   active-charity counts, weekly for grant aggregates. Lower cadence
   = staler cache; higher cadence = more upstream traffic. Daily is
   well within polite API budgets at ~330 LTLAs.
2. **Should `find_organisations_in_place` cap on the number of
   passthrough fan-outs?** Plan default: yes, fan-out goes to at
   most 2 adapters per call (one E&W or one Scotland/NI, plus
   optional grants enrichment). Avoids unbounded latency stacking.
3. **`grants_in_last_12m_*` semantics — beneficiary-based or
   recipient-address-based?** Plan default: beneficiary
   (`recipientLocations` in 360G's payload). Note coverage gap — many
   records lack beneficiary postcode; the figure undercounts. Caveat
   it.
4. **TTL for `civil_society.active_charities_count`?** Plan default:
   24h. CC publishes daily; same-day staleness is acceptable.

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

## Block A — Charity Commission passthrough (Tasks 4–9)

### Task 4: `CharityCommissionClient`

**Files:**
- Create: `server/soundings/adapters/charity_commission/__init__.py`
- Create: `server/soundings/adapters/charity_commission/client.py`
- Create: `server/tests/test_cc_client.py`

Wraps the CC REST API at `https://api.charitycommission.gov.uk/`.
Reads `CHARITY_COMMISSION_API_KEY` from env, forwards as
`Ocp-Apim-Subscription-Key`. Methods we need:

- `search_charities(postcode_area: str, page: int = 1, page_size: int = 100)` —
  returns the JSON with `totalReturned` + paginated rows.
- `count_charities_in_area(postcode_area_prefix: str)` — calls search
  with `page_size=1`, reads `totalReturned`. Cheap one-shot count.
- `get_charity(reg_number: int)` — single charity detail.

Rate limit per public-tier guidance (~5 RPS). Mock-transport tests
confirm headers / query string / pagination shape.

Commit: `feat(adapters): charity commission async client`.

### Task 5: `CharityCommissionAdapter` (passthrough)

**Files:**
- Create: `server/soundings/adapters/charity_commission/adapter.py`
- Create: `server/tests/test_cc_adapter.py`

`source_id = "charity_commission"`, `mode = "passthrough"`,
`ttl=timedelta(hours=24)`.

- `fetch_indicator(civil_society.active_charities_count, place_id)` →
  resolve `place_id` → postcode area prefix (via `geography.place` +
  cached `geography.postcode` lookups), call
  `client.count_charities_in_area`, return `IndicatorValue`.
- `fetch_indicator(civil_society.active_charities_per_10k, place_id)` →
  call count above, divide by latest `population.total`, return.
- `fetch_organisations(place_id, filters, limit)` → paginate
  `client.search_charities` up to `limit`, materialise each row as
  `OrganisationRef` with `source` stamped.

Cache key shape: `f"cc:{indicator_or_orgs}:{place_id}"`. Adapter
test mocks the client + asserts the count fan-out + organisation
materialisation.

Commit: `feat(adapters): CharityCommissionAdapter passthrough`.

### Task 6: CC pre-warmer

**Files:**
- Modify: `server/soundings/adapters/charity_commission/adapter.py`
- Create: `server/tests/test_cc_pre_warm.py`

Override `pre_warm_for_places(place_ids)` to fetch the count
indicator for every supplied LTLA, populating `cache.source_cache`
under the same keys `fetch_indicator` would read.

Commit: `feat(adapters): CC pre_warm_for_places(ltlas) for count cache`.

### Task 7: Register CC adapter

**Files:**
- Modify: `server/soundings/app.py`

Wire `CharityCommissionAdapter` into `AdapterRegistry`.

Commit: `feat(app): register charity_commission + civil_society indicators`.

### Task 8: Live test for the CC adapter

**Files:**
- Create: `server/tests/live/test_cc_live.py`

Marker `live` + `integration`. Skips cleanly without
`CHARITY_COMMISSION_API_KEY`. With a key:

- `count_charities_in_area("TS18")` returns a plausible integer.
- `fetch_organisations` for `ltla24:E06000004` returns ≥1 charity
  with a non-empty name.

Commit: `test: cc live smoke for stockton`.

### Task 9: Block A docs

**Files:**
- Modify: `STATE.md`
- Modify: `PLAN.md`

Commit: `docs: block a — cc passthrough live`.

PR title: `Phase 4 Block A: Charity Commission passthrough adapter`.

---

## Block B — 360Giving passthrough (Tasks 10–14)

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

## Block C — Find That Charity passthrough (Tasks 15–18)

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

## Block D — `find_organisations_in_place` tool (Tasks 19–24)

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

1. Resolve `geography.place(id)` to fetch `country` + `type`.
2. Pick a primary adapter:
   - England / Wales → `charity_commission`
   - Scotland / NI → `find_that_charity`
3. Call `adapter.fetch_organisations(place_id, filters, limit)`.
4. Optionally enrich each result with `threesixtygiving.recent_grants`
   (only when `funded_only=true` or as a default top-3 summary).
5. Return list + dedup-ed SourceRefs + any caveats from the adapters.

Returns partial=True if any adapter errors out, mirroring the
existing `compare_places` orchestrator pattern.

Test seeds catalogue + the cache.source_cache with two synthetic CC
responses for two LTLAs; asserts the right adapter is picked + the
grants enrichment fires when `funded_only=true`.

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

## Block E — UI surface for organisations (Tasks 25–27)

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

## Block F — Integration, e2e, tag (Tasks 28–31)

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

Like the Phase 3 runbook. Notes the new `pre_warmer` service +
how to seed its cache for the smoke (one-shot `python -m
soundings.pre_warmer.run --once charity_commission`).

Commit: `docs(runbook): phase 4 browser smoke`.

### Task 30: Update STATE.md + PLAN.md

**Files:**
- Modify: `STATE.md`
- Modify: `PLAN.md`

Mark Phase 4 complete, list Phase 5 follow-ups.

Commit: `docs: phase 4 complete — three passthrough adapters + find_organisations`.

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
- [ ] Three new passthrough adapters live: `charity_commission`,
      `threesixtygiving`, `find_that_charity`.
- [ ] `pre_warmer` service running in compose, warming the cache for
      civil-society indicators on a daily/weekly cron.
- [ ] No new rows in `data.organisation` or `data.grant_record`
      (Phase 4 doesn't touch them; v2 enrichment work will).
- [ ] `/place/[id]` renders an Organisations section for E&W places
      and degrades cleanly elsewhere.
- [ ] Nightly live tests for all three new adapters green.
- [ ] `STATE.md` + `PLAN.md` updated, `v0.5.0-phase-4` tagged.

## Out of scope

- Phase 5+ work — separate plan documents.
- `data.organisation` / `data.grant_record` population — v2 enrichment.
- ICNPO ↔ CC activity-code mapping — v2 task.
- Operational-reach geography (`operates_in` beyond registered
  address) — v2 task using FTC's geo joins.
- Backfilling earlier Phase 1 loaders (MYE / Census / IMD) to
  passthrough — the API-first principle applies forward only; the
  existing loaders ship value and stay.

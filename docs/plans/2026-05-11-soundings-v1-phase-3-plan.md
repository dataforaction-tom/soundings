# Soundings v1 — Phase 3 Implementation Plan

> **For Claude:** Same TDD-per-task / commit-per-task discipline as
> Phases 0, 1, and 2. Conventions, commit prefixes, exact file paths.

**Goal:** Four new passthrough adapters, two new tools, time-series
storage, and charts on the UI. Phase 3 ends when:

1. Tools `compare_places` and `get_trend` are live on HTTP + MCP.
2. Indicators for **health** (Fingertips), **welfare** (Stat-Xplore),
   **education** (DfE Explore), **crime** (police.uk), and **labour
   market** (ONS APS) are reachable through `get_indicators` and the
   two new tools.
3. `/place/[id]` shows a trend sparkline per indicator card; a new
   `/compare` page renders rank/percentile/value bar charts across
   multiple places.
4. Observable Plot is wired in (server-rendered SVG, no client JS).
5. Live tests for all four new adapters run nightly.

**Architecture:** Per `docs/plans/2026-05-05-soundings-v1-design.md` §3
(`PassthroughAdapter` base class), §4 (orchestrator behaviours and
HTTP routes), §2 (`data.trend_point` table). The passthrough TTLs come
from `catalogue/sources.yaml` (already populated for these sources).
Phase 1 already wired `PassthroughAdapter.fetch_indicator` through
`source_cache` + retries + rate limiting; Phase 3 adapters extend
that, plus a new `fetch_trend` method for series.

**Tech stack additions on top of Phase 2:**

| Dep | Purpose | Asked? |
|---|---|---|
| `@observablehq/plot` | Server-rendered SVG charts on the UI | Yes — design §4 |
| `linkedom` | DOM polyfill so `@observablehq/plot` renders in SSR (Node has no native `document`). Plot calls `document.createElement` internally and will crash without this. | New (forced by Plot's DOM requirement) |
| (no new Python deps) | All adapters use existing httpx + aiolimiter | n/a |

**Estimated scope:** ~45 tasks across 10 blocks. ~2 focused weeks per
spec §13. Five adapters can be parallelised once Block A's contracts
land — Blocks B–F are independent of each other. **If time pressure
hits**, Block I (UI charts) can split into a Phase 3.5 release: the
two new tools and five adapters ship as `v0.4.0-phase-3`, charts as
`v0.4.1-phase-3-charts` once the DOM-polyfill work is settled.

**Prerequisites Tom needs to do once before starting:**

- Register for a **DWP Stat-Xplore API key** (free, instant via
  <https://stat-xplore.dwp.gov.uk/>). Store as `STATXPLORE_API_KEY` in
  `soundings-ops` **and add to GitHub Actions Secrets** so the nightly
  live test can pass — without this, Task 16's live test always skips
  and the "live tests pass nightly" done criterion can't be verified.
- Confirm whether OHID Fingertips needs registration (it didn't at
  Phase 0 spec time — public). If anything's changed, surface as a
  Block B blocker.
- Decide whether to enable spaCy NER + DB-backed name lists in the
  production sanitiser at the same time as Phase 3 (a small Phase 2
  follow-up bundled in Block A here).

---

## Conventions used in this plan

- **TDD throughout.** Every behaviour task: failing test → minimum
  implementation → green → commit.
- **Commits per task** with conventional-commits prefixes (`feat`,
  `chore`, `test`, `refactor`, `docs`, `ci`).
- **Exact file paths** relative to repo root unless prefixed `/`.
- **Live tests** for every new adapter under `server/tests/live/`.
  Mock-transport tests for non-live PR-time coverage.
- **No new Python dep additions** in Phase 3 — all adapters reuse the
  httpx + aiolimiter stack.

---

## Block A — Schema + contracts + Phase 2 loose-ends (Tasks 1–6)

### Task 1: Migration 0006 — `data.trend_point` table

**Files:**
- Create: `server/soundings/db/migrations/versions/0006_trend_point_table.py`
- Modify: `server/soundings/db/models/data.py`
- Create: `server/tests/test_trend_point_schema.py`

```sql
CREATE TABLE data.trend_point (
  place_id     VARCHAR REFERENCES geography.place(id),
  indicator_key VARCHAR REFERENCES catalogue.indicator(key),
  period       VARCHAR,            -- ISO period (e.g. "2024", "2024-Q2")
  value        NUMERIC,
  revised      BOOLEAN DEFAULT FALSE,
  source_id    VARCHAR REFERENCES catalogue.source(id),
  retrieved_at TIMESTAMPTZ,
  PRIMARY KEY (place_id, indicator_key, period)
);
CREATE INDEX ON data.trend_point (place_id, indicator_key);
```

Test: insert + select round-trip, FK enforcement (unknown place fails).

Commit: `feat(db): trend_point table for time-series storage`.

### Task 2: `TrendPoint` + `Trend` Pydantic contracts

**Files:**
- Create: `server/soundings/contracts/trend.py`
- Create: `server/tests/test_trend_contracts.py`

```python
class TrendPoint(BaseModel):
    period: str
    value: float | None
    revised: bool = False

class Trend(BaseModel):
    place_id: str
    indicator: str
    unit: str
    points: list[TrendPoint]
    source: SourceRef
    breaks_in_series: list[str] = Field(default_factory=list)
```

**`breaks_in_series` population rule:** filter
`indicator.caveats` entries by **string prefix** `series_break:` —
e.g. `"series_break: methodology changed 2018"` becomes
`"methodology changed 2018"` in the trend response.
`catalogue/indicators.yaml` carries them under each indicator's
`caveats:` list. This is the v1 convention; v1.5 may move to a
structured `series_breaks:` list on the catalogue entry.

Round-trip test through JSON.

Commit: `feat(contracts): TrendPoint + Trend pydantic models`.

### Task 3: `ComparisonValue` + `Comparison` Pydantic contracts

**Files:**
- Create: `server/soundings/contracts/comparison.py`
- Create: `server/tests/test_comparison_contracts.py`

```python
class ComparisonValue(BaseModel):
    place_id: str
    value: float | None
    rank: int | None = None
    percentile: float | None = None

class Comparison(BaseModel):
    indicator: str
    unit: str
    period: str
    values: list[ComparisonValue]
    source: SourceRef
    methodology_note: str | None = None  # deliberate extension of spec §4.4
    caveats: list[str] = Field(default_factory=list)  # deliberate extension
```

`methodology_note` and `caveats` are present on every other
indicator-bearing response (`IndicatorValue`, the prior tools); their
absence on `Comparison` would be a surprise for downstream consumers.
Treating as a **deliberate extension** of the spec contract — flag in
the commit message so a future reviewer doesn't trim them.

Commit: `feat(contracts): Comparison + ComparisonValue pydantic models`.

### Task 4: `PassthroughAdapter.fetch_trend` default + cache key

**Files:**
- Modify: `server/soundings/adapters/passthrough_base.py`
- Create: `server/tests/test_passthrough_adapter_fetch_trend.py`

Add an abstract `fetch_trend(indicator_key, place_id, period_from,
period_to) -> Trend | None` to `PassthroughAdapter`. Default
implementation walks `source_cache` with a key like
`<indicator>:<place_id>:trend:<from>-<to>` and routes to a
subclass-provided `_call_upstream_trend`.

Test: a fake adapter returns a 5-point series; cache hit and TTL
expiry behave like `fetch_indicator`.

Commit: `feat(adapters): PassthroughAdapter.fetch_trend with TTL caching`.

### Task 5: Wire production sanitiser pipeline (Phase 2 follow-up)

**Files:**
- Modify: `server/soundings/app.py`
- Create: `server/soundings/capture/sanitisation/build.py`
- Create: `server/tests/test_sanitisation_pipeline_build.py`

`build_default_pipeline(engine, config) -> SanitisationPipeline` loads
LSOA/MSOA names from `geography.place` and small-org names from
`data.organisation` (empty for now), instantiates
`StripPersonalNamesViaNER`, and composes the full six-rule pipeline.
The app lifespan calls this instead of the three-rule subset wired in
Phase 2.

Test: builder returns a pipeline whose `_rules` list has six entries
in the right order; the fine_geography rule's name list contains a
seeded LSOA name.

Commit: `feat(capture): production pipeline assembles full rule set`.

### Task 6: Vitest in CI (Phase 2 follow-up)

**Files:**
- Modify: `.github/workflows/ci.yml`

Adds a `ui` job to ci.yml: `node:20`, `npm ci`, `npm test`,
`npm run typecheck`. Runs in parallel with the existing `lint-type` +
`test` jobs.

Commit: `chore(ci): run UI Vitest + typecheck on every push`.

---

## Block B — OHID Fingertips adapter (Tasks 7–11)

OHID Fingertips is a public REST API at
<https://fingertips.phe.org.uk/api/>. No auth (re-verify at Task 7).

### Task 7: `FingertipsClient` — async wrapper

**Files:**
- Create: `server/soundings/adapters/ohid_fingertips/__init__.py`
- Create: `server/soundings/adapters/ohid_fingertips/client.py`
- Create: `server/tests/test_fingertips_client.py`

`get_indicator_data(indicator_id, area_codes, area_type_id)` returns
the JSON. Rate-limited to 4 RPS. Errors propagate.

Test: `httpx.MockTransport` mock — assert URL contains the expected
query params.

Commit: `feat(adapters): OHID Fingertips async HTTP client`.

### Task 8: Fingertips indicator mapping

**Files:**
- Create: `catalogue/fingertips-mapping.yaml`
- Create: `server/soundings/adapters/ohid_fingertips/mapping.py`
- Create: `server/tests/test_fingertips_mapping.py`

Maps each `health.*` indicator key to a Fingertips
`(indicator_id, area_type_id)`. Examples (verify live):

```yaml
- indicator_key: health.life_expectancy.female
  indicator_id: 90366
  area_type_id: 102   # ltla24
- indicator_key: health.healthy_life_expectancy.female
  indicator_id: 92543
  area_type_id: 102
```

Commit: `feat(catalogue): fingertips-mapping.yaml + loader`.

### Task 9: `OhidFingertipsAdapter` passthrough

**Files:**
- Create: `server/soundings/adapters/ohid_fingertips/adapter.py`
- Create: `server/tests/test_fingertips_adapter.py`

Implements `fetch_indicator` **and `fetch_trend`** (Fingertips
publishes annual time series — series is fundamental to the
indicator). Materialises the Fingertips JSON into `IndicatorValue` /
`Trend`. Uses `source_cache` with 24h TTL via the base.

Test (mock transport): one indicator, two places; assert correct
upstream URL, correct `IndicatorValue.value` for each. A separate
`fetch_trend` test asserts a 5-point ordered series.

Commit: `feat(adapters): OhidFingertipsAdapter passthrough`.

### Task 10: Register Fingertips in app + registry

**Files:**
- Modify: `server/soundings/app.py`
- Modify: `catalogue/indicators.yaml` (add `health.*` entries)

Adapter registered in the `AdapterRegistry` so `get_indicators` can
route to it. Add ~5 health indicator entries to `indicators.yaml`.

Commit: `feat(app): register Fingertips adapter + health indicators`.

### Task 11: Live test for Fingertips

**Files:**
- Create: `server/tests/live/test_fingertips_live.py`

Stockton LTLA, `health.life_expectancy.female`. **Asserts a plausible
non-null value (75–90)** so a Fingertips API/indicator-ID retirement
fails nightly rather than silently returning no-data.

Commit: `test: fingertips live smoke for Stockton life expectancy`.

---

## Block C — DWP Stat-Xplore adapter (Tasks 12–16)

Stat-Xplore is a SOAP-ish JSON API at
<https://stat-xplore.dwp.gov.uk/webapi/rest/v1/>. Requires
`STATXPLORE_API_KEY` in the `APIKey` header. Free signup.

### Task 12: `StatXploreClient`

**Files:**
- Create: `server/soundings/adapters/dwp_statxplore/client.py`
- Create: `server/tests/test_statxplore_client.py`

POSTs to `/table` with a JSON cube definition. Honours
`STATXPLORE_API_KEY` from env. 2 RPS limit.

Test: mock transport, assert `APIKey` header and POST body shape.

Commit: `feat(adapters): DWP Stat-Xplore async HTTP client`.

### Task 13: Stat-Xplore cube mapping

**Files:**
- Create: `catalogue/statxplore-mapping.yaml`
- Create: `server/soundings/adapters/dwp_statxplore/mapping.py`

Maps each `welfare.*` indicator key to a Stat-Xplore cube + dimension
selectors. Verify live for caseload + child poverty AHC.

Commit: `feat(catalogue): statxplore-mapping.yaml`.

### Task 14: `DwpStatXploreAdapter`

**Files:**
- Create: `server/soundings/adapters/dwp_statxplore/adapter.py`
- Create: `server/tests/test_statxplore_adapter.py`

`fetch_indicator` + `fetch_trend`. 24h TTL.

Commit: `feat(adapters): DwpStatXploreAdapter passthrough`.

### Task 15: Register Stat-Xplore in app + welfare indicators

**Files:**
- Modify: `server/soundings/app.py`
- Modify: `catalogue/indicators.yaml`

Commit: `feat(app): register Stat-Xplore + welfare indicators`.

### Task 16: Live test for Stat-Xplore

**Files:**
- Create: `server/tests/live/test_statxplore_live.py`

Skip with a clear message if `STATXPLORE_API_KEY` isn't set. **Live
key MUST be in GitHub Actions Secrets** (added in the prerequisites)
so nightly CI actually exercises this adapter.

Commit: `test: statxplore live smoke for Stockton claimants`.

---

## Block D — DfE Explore Education Statistics adapter (Tasks 17–20)

REST API at
<https://content.explore-education-statistics.service.gov.uk/api/>.
No auth. Each indicator binds to a (publication, releaseId, dataSetId,
filter, indicator). DfE republishes datasets annually with new IDs;
our only mitigation in v1 is the live test (Task 20) asserting a
plausible value — a retired ID then fails nightly rather than
silently returning no-data.

### Task 17: `DfEExploreClient`

**Files:**
- Create: `server/soundings/adapters/dfe_explore/client.py`
- Create: `server/tests/test_dfe_client.py`

POSTs to `/data-sets/{id}/query` with a filter + indicator body.

Commit: `feat(adapters): DfE Explore Education Statistics async client`.

### Task 18: DfE indicator mapping

**Files:**
- Create: `catalogue/dfe-mapping.yaml`
- Create: `server/soundings/adapters/dfe_explore/mapping.py`

Maps `education.*` indicators to dataset IDs + indicator IDs.

Commit: `feat(catalogue): dfe-mapping.yaml`.

### Task 19: `DfeExploreAdapter`

**Files:**
- Create: `server/soundings/adapters/dfe_explore/adapter.py`
- Create: `server/tests/test_dfe_adapter.py`

`fetch_indicator` + `fetch_trend`. 24h TTL.

Commit: `feat(adapters): DfeExploreAdapter passthrough`.

### Task 20: Register DfE + live test (plausible value)

**Files:**
- Modify: `server/soundings/app.py`
- Modify: `catalogue/indicators.yaml`
- Create: `server/tests/live/test_dfe_live.py`

**Live test asserts a plausible FSM eligibility share (0–100%)**
so a retired DfE dataset ID fails nightly rather than silently
returning no-data.

Commit: `feat(app): register DfE + education indicators` and
`test: dfe live smoke for FSM eligibility`.

---

## Block E — police.uk adapter (Tasks 21–23)

REST API at <https://data.police.uk/docs/>. No auth.
`/crimes-street/{category}?lat=…&lng=…&date=…` returns crimes within
a ~1-mile circle of the lat/lng, **not a polygon bounded by the LTLA
shape**. For large or geographically dispersed LTLAs (Cornwall,
Highland) this undercounts by a significant fraction. v1 ships this
with a fixed methodology caveat on every returned value; an exact
polygon-bounded aggregation is a v1.5 task.

### Task 21: `PoliceUkClient`

**Files:**
- Create: `server/soundings/adapters/police_uk/client.py`
- Create: `server/tests/test_police_uk_client.py`

`get_crimes(category, lat, lng, date)` returns the JSON.

Commit: `feat(adapters): police.uk async client`.

### Task 22: `PoliceUkAdapter` with LTLA aggregation + methodology caveat

**Files:**
- Create: `server/soundings/adapters/police_uk/adapter.py`
- Create: `server/tests/test_police_uk_adapter.py`

Pulls LTLA centroid lat/lng from `geography.place`, fetches monthly
crime counts, aggregates and rate-converts using MYE population.
**Every returned `IndicatorValue` carries a fixed caveat:**

> `"Crime count is centroid-proximate (police.uk API returns crimes within ~1 mile of the supplied lat/lng), not LTLA-boundary accurate; underestimates large or dispersed LTLAs."`

The caveat is asserted by the adapter test so a future refactor
removing it fails CI.

Commit: `feat(adapters): PoliceUkAdapter with centroid-aggregation caveat`.

### Task 23: Register police.uk + live test

**Files:**
- Modify: `server/soundings/app.py`
- Modify: `catalogue/indicators.yaml`
- Create: `server/tests/live/test_police_uk_live.py`

Commit: `feat(app): register police.uk + crime indicators` and
`test: police.uk live smoke for Stockton total recorded crime`.

---

## Block F — ONS APS adapter (Tasks 24–26)

ONS Annual Population Survey is delivered via Nomis (the same
`NomisClient` already used by `ons.mid_year_estimates`). Adapter is
thin — pin the dataset ID, reuse client, separate source_id for
provenance.

### Task 24: APS adapter with `fetch_indicator` + `fetch_trend`

**Files:**
- Modify: `catalogue/nomis-mapping.yaml`
- Create: `server/soundings/adapters/ons_aps/adapter.py`
- Create: `server/tests/test_aps_adapter.py`

Map `labour_market.*` indicators (employment rate, claimant count,
median pay) to `(dataset_id, measures, c_age, gender, ...)`. APS is a
quarterly time series; `fetch_trend` is **required** on this adapter
just like Fingertips. Reuses `NomisClient` with a `time` range
parameter.

Commit: `feat(adapters): ons.aps adapter via NomisClient with trend`.

### Task 25: Register APS + labour market indicators

**Files:**
- Modify: `server/soundings/app.py`
- Modify: `catalogue/indicators.yaml`

Commit: `feat(app): register ons.aps + labour market indicators`.

### Task 26: Live test for APS

**Files:**
- Create: `server/tests/live/test_aps_live.py`

Asserts a plausible Stockton employment rate (0.5–0.85 fraction).

Commit: `test: aps live smoke for Stockton employment rate`.

---

## Block G — `compare_places` tool (Tasks 27–31)

### Task 27: Tool spec + Pydantic request/response

**Files:**
- Create: `server/soundings/tools/compare_places.py`
- Create: `server/tests/test_tool_compare_places_spec.py`

Spec §4.4 shape. `comparison_basis` is **explicitly optional with no
default in spec §4.4**; this plan ships with **default `"percentile"`**
because (a) percentile against same-type peers is the most useful
default for "how does my place compare", and (b) the spec leaves the
default open. Note that as a plan decision in the commit message.

Test: round-trip empty request/response through Pydantic.

Commit: `feat(tools): compare_places tool schema (default basis=percentile)`.

### Task 28: Orchestrator method — percentile against the full peer universe

**Files:**
- Modify: `server/soundings/orchestration/orchestrator.py`
- Create: `server/tests/test_orchestrator_compare.py`

`compare_places(place_ids, indicators, basis)`:

1. Fetch the indicator value for **every same-type peer**, not just
   the caller's `place_ids`. The "same type" is inferred from the
   first place_id's type (e.g. `ltla24:…` → all `ltla24` places). The
   caller's list is the highlighted subset; the full type-universe is
   the denominator for ranks and percentiles.
2. Read the peer-universe values from `data.indicator_value` directly
   for loader-mode adapters (cheap SELECT). For passthrough-mode
   adapters, fall back to fan-out `fetch_indicator(place_id)` ×
   peers, with a soft budget — if > 200 peer fetches would be needed
   for a passthrough indicator, return the caller's places only with a
   caveat `"percentile computed against caller-provided peers only;
   indicator is passthrough-mode at this granularity"`.
3. Order: `basis="percentile"` attaches `percentile` + `rank`;
   `basis="rank"` attaches `rank`; `basis="absolute"` no extras;
   `basis="rate"` divides through by a population denominator (MYE
   for the place-type) before ranking. spec §4.4 lists all four.

Test: seed 11 ltla24 places with known values (5 lower, 5 higher than
the requested place), assert the requested place's percentile is 50.

Commit: `feat(orchestrator): compare_places — percentile against full peer universe`.

### Task 29: HTTP route `/v1/tools/compare_places`

**Files:**
- Modify: `server/soundings/http/tools.py`
- Create: `server/tests/test_http_compare_places.py`

Standard JSON POST.

Commit: `feat(http): POST /v1/tools/compare_places`.

### Task 30: MCP registration

**Files:**
- Modify: `server/soundings/mcp/server.py`

Add tool registration. Same handler.

Commit: `feat(mcp): register compare_places tool`.

### Task 31: e2e via both transports

**Files:**
- Create: `server/tests/test_phase_3_e2e_compare.py`

Commit: `test: compare_places e2e via HTTP + MCP`.

---

## Block H — `get_trend` tool (Tasks 32–35)

### Task 32: Tool spec + Pydantic shape

**Files:**
- Create: `server/soundings/tools/get_trend.py`
- Create: `server/tests/test_tool_get_trend_spec.py`

Spec §4.5 shape.

Commit: `feat(tools): get_trend tool schema`.

### Task 33: Orchestrator method

**Files:**
- Modify: `server/soundings/orchestration/orchestrator.py`
- Create: `server/tests/test_orchestrator_get_trend.py`

Routes to `adapter.fetch_trend(indicator, place_id, period_from,
period_to)`. Loader-mode adapters read `data.trend_point`. Passthrough
adapters call upstream + cache.

`breaks_in_series` populated from `indicator.caveats` filtered by
`"series_break:"` prefix (per Task 2's convention).

Test: seed `trend_point` rows for an LTLA, fetch through orchestrator,
assert ordered series; seed a `series_break:` caveat on the catalogue
indicator, assert it surfaces.

Commit: `feat(orchestrator): get_trend routes by adapter mode`.

### Task 34: HTTP + MCP

**Files:**
- Modify: `server/soundings/http/tools.py`
- Modify: `server/soundings/mcp/server.py`
- Create: `server/tests/test_http_get_trend.py`

Commit: `feat(http+mcp): register get_trend tool`.

### Task 35: e2e

**Files:**
- Create: `server/tests/test_phase_3_e2e_trend.py`

Commit: `test: get_trend e2e via HTTP + MCP`.

---

## Block I — UI charts + comparison page (Tasks 36–41)

> **If time pressure hits**, this entire block can be deferred to a
> point release `v0.4.1-phase-3-charts`. The two new tools + five
> adapters ship as `v0.4.0-phase-3` without UI changes.

### Task 36: Add `@observablehq/plot` + DOM polyfill

**Files:**
- Modify: `ui/package.json`
- Modify: `ui/package-lock.json`
- Create: `ui/src/lib/dom-polyfill.ts`

Pin stable versions of `@observablehq/plot` and `linkedom`.
`linkedom` is required because `@observablehq/plot` mutates the DOM
(`document.createElement`) internally; Node SSR has no native
`document`. `dom-polyfill.ts` exports a side-effect-only module that
sets `globalThis.document` etc. from linkedom. Every chart component
imports `"../lib/dom-polyfill"` before importing Plot.

Commit: `chore(ui): add @observablehq/plot + linkedom (DOM polyfill)`.

### Task 37: Update `lib/api.ts` for the two new tools

**Files:**
- Modify: `ui/src/lib/api.ts`
- Modify: `ui/src/lib/types.ts`
- Modify: `ui/tests/api.test.ts`

`comparePlaces(placeIds, indicators, basis)` + `getTrend(placeId,
indicator, periodFrom, periodTo)`. TypeScript mirrors of
`Comparison`, `ComparisonValue`, `Trend`, `TrendPoint`.

Lands **before** the chart components (Tasks 38–40) consume the new
calls.

Commit: `feat(ui): typed wrappers for compare_places + get_trend`.

### Task 38: `IndicatorChart.astro` — server-rendered SVG sparkline

**Files:**
- Create: `ui/src/components/IndicatorChart.astro`
- Create: `ui/src/lib/chart.ts`
- Create: `ui/tests/chart.test.ts`

Imports `../lib/dom-polyfill` first. Then a pure
`renderSparkline(points)` returns the SVG string via
`Plot.plot({...}).outerHTML`. The `.astro` wraps in a `<figure>` with
caption.

Test: a 5-point series produces an SVG containing 5 data shapes.

Commit: `feat(ui): IndicatorChart server-rendered sparkline`.

### Task 39: `/place/[id]` adds trend per card

**Files:**
- Modify: `ui/src/pages/place/[id].astro`
- Modify: `ui/src/components/IndicatorCard.astro`

For each indicator, optionally request a trend (only for indicators
whose adapter exposes `fetch_trend`). Pass `points` into
`IndicatorChart` if present.

Commit: `feat(ui): trend sparklines on /place/[id]`.

### Task 40: `/compare` page

**Files:**
- Create: `ui/src/pages/compare.astro`
- Create: `ui/src/components/CompareChart.astro`
- Create: `ui/tests/compare_chart.test.ts`

Accepts `?places=a,b,c&indicators=x,y` query string. Calls
`compare_places`. Renders a bar chart per indicator (places on X
axis, value on Y axis, percentile badge per bar).

Commit: `feat(ui): /compare page with side-by-side bar charts`.

### Task 41: Update `/about` to mention the new tools

**Files:**
- Modify: `ui/src/pages/about.astro`

Two sentences explaining compare + trend.

Commit: `docs(ui): /about mentions compare + trend`.

---

## Block J — Integration, e2e, tag (Tasks 42–45)

### Task 42: Phase 3 e2e — server-side, no UI

**Files:**
- Create: `server/tests/test_phase_3_e2e.py`

Seeds population + a Fingertips indicator + 3 trend points; POSTs
`compare_places` for 3 LTLAs and `get_trend` for one. Asserts the
ranked response and a 3-point series.

Commit: `test: phase 3 e2e — compare + trend + Fingertips passthrough`.

### Task 43: Manual browser smoke (no test, just a runbook bullet)

**Files:**
- Modify: `docs/runbook-mac-mini-deploy.md` (or new `docs/runbook-phase-3-smoke.md`)

Documents the manual click-through:
1. `/place/ltla24:E06000004` shows sparklines for indicators that
   have trends.
2. `/compare?places=ltla24:E06000004,ltla24:E08000001&indicators=population.total,deprivation.imd.score`
   shows side-by-side bars + percentile badges.

Commit: `docs(runbook): phase 3 browser smoke`.

### Task 44: Update STATE.md / PLAN.md

**Files:**
- Modify: `STATE.md`
- Modify: `PLAN.md`

Mark Phase 3 done, list Phase 4 follow-ups.

Commit: `docs: phase 3 complete — five new adapters + compare + trend + charts`.

### Task 45: Tag `v0.4.0-phase-3`

**Steps:**

1. `make lint && make type && make test && make test-integration`.
2. `make up && make migrate && make seed-light`.
3. Browser smoke per Task 43 runbook.
4. Tag + push:

```bash
git tag -a v0.4.0-phase-3 -m "phase 3: 5 new adapters, compare + trend, charts"
git push origin v0.4.0-phase-3
```

---

## Done criteria for Phase 3

All green simultaneously:

- [ ] `POST /v1/tools/compare_places` accepts a list of place_ids +
      indicators, returns `Comparison[]` with rank/percentile when
      applicable. Percentile is computed against the **full peer
      universe**, not just the caller's list.
- [ ] `POST /v1/tools/get_trend` returns ordered `TrendPoint[]` for a
      place + indicator, supports `period_from` + `period_to`.
      `breaks_in_series` populated from `series_break:`-prefixed
      caveats.
- [ ] Five new adapters wired through the registry: Fingertips,
      Stat-Xplore, DfE Explore, police.uk, ons.aps. Police.uk results
      carry the centroid-aggregation methodology caveat.
- [ ] `catalogue/indicators.yaml` has ~25+ indicators across health,
      welfare, education, crime, labour market.
- [ ] `/place/[id]` renders sparklines per card for indicators that
      have trend data.
- [ ] `/compare` page exists and renders correctly for 2–10 places.
- [ ] Live tests for the four genuinely new adapters
      (Fingertips + Stat-Xplore + DfE + police.uk) pass nightly.
      `STATXPLORE_API_KEY` is set in GitHub Actions Secrets.
- [ ] Vitest runs in CI on every push.
- [ ] Production sanitiser pipeline composes the full six-rule set.
- [ ] CI green on `main`.
- [ ] Tag `v0.4.0-phase-3` pushed.

---

## Deferred from Phase 3 (with explicit reasons)

| Deferred item | Why | Phase |
|---|---|---|
| Charity Commission + 360Giving + Find That Charity adapters | Civil-society block; bundled in Phase 4. | 4 |
| `find_organisations_in_place` tool | Needs the Phase 4 adapters' data. | 4 |
| Stat-Xplore key-rotation flow | Single key is fine for v1; rotation is a v1.5 ops task. | v1.5 |
| Police.uk polygon-bounded aggregation | Centroid-proximate is the v1 trade-off with explicit caveat; polygon work needs PostGIS query design. | v1.5 |
| Compare-with-peers shortcut button on `/place/[id]` | UI polish that requires a population-sort over `geography.place`; deferred so Block I doesn't bloat. | 6 |
| Structured `series_breaks:` list in `indicators.yaml` | Phase 3 uses a `series_break:` string prefix on caveats; if that gets unwieldy, restructure in v1.5. | v1.5 |
| IMD 2025 deciles (File 2) | Phase 2 follow-up; doesn't gate Phase 3. | 3 follow-up |
| Permanent-orphan pending stub cron | ADR-0003 edge case; revisit if backlog accumulates. | 3 follow-up |

---

## What's next (preview, not in this plan)

**Phase 4** — Civil-society adapters (Charity Commission, 360Giving,
Find That Charity) and the `find_organisations_in_place` tool. Plus a
small UI surface for "organisations operating here" on `/place/[id]`.

*End of Phase 3 plan.*

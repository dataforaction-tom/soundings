# Soundings v1 — Phase 1 Implementation Plan

> **For Claude:** Same TDD-per-task / commit-per-task discipline as Phase 0
> (`docs/plans/2026-05-05-soundings-v1-phase-0-plan.md`). Conventions, commit
> prefixes, and "exact file paths" rules carry over.

**Goal:** Stand up the indicator pipeline end-to-end. Phase 1 ends when an
HTTP or MCP client can call `get_indicators("population.total",
"ltla24:E06000004")` against a `make seed-light`-ed stack and receive a
provenanced `IndicatorValue` with `source_id`, `period`, and `cache_status`.
Three indicator-bearing source adapters (`ons.mid_year_estimates`,
`ons.census2021`, `mhclg.imd2025`) and three tools (`find_place`,
`get_indicators`, `get_place_profile`) are live, on both transports.

**Architecture:** Per `docs/plans/2026-05-05-soundings-v1-design.md` §3
(SourceAdapter protocol, two base classes, cache-status rules), §4
(orchestrator behaviours, HTTP routes, error shape). New runtime: a
`loader` Docker service runs APScheduler over the same image as `server`
and triggers loader runs on each source's `refresh_cadence`. The
`server` continues to serve reads only; loaders never run inside `server`.

**Tech stack additions on top of Phase 0:**
`mcp[cli] >= 1.2`, `apscheduler >= 3.10`, `openpyxl >= 3.1`
(IMD parses the published `.xlsx`).

**Estimated scope:** ~52 bite-sized tasks across 10 blocks. ~2–3 focused
weeks if Phase 0 is the calibration baseline.

**Prerequisites Tom needs to do once before starting:**

- Decide whether the Nomis API key (optional, only needed at high RPS) goes
  in `soundings-ops`. v1 default is to run unauthenticated at 2 RPS.
- Phase 0 OGP URL verification — at least the LTLA24 BUC layer should be
  confirmed in `docs/adr/0001-geography-data-sources.md` before Phase 1
  loaders run, since the e2e test seeds against a real LTLA code.

---

## Conventions used in this plan

- **TDD throughout** (same as Phase 0). Every behaviour task: failing test
  → minimum implementation → green → commit. Pure scaffolding skips the test
  step but still commits.
- **Commits per task** with conventional-commits prefixes (`feat`, `chore`,
  `test`, `refactor`, `docs`, `ci`).
- **Exact file paths.** All paths relative to repo root unless prefixed `/`.
- **All new HTTP fixture data** lives under `server/tests/fixtures/<source_id>/`
  (Census table dumps, IMD spreadsheet excerpts) so tests stay deterministic
  without hitting the network.
- **Live tests** for every source adapter live in `server/tests/live/` and
  are marked `@pytest.mark.live`. They run nightly in CI and are not part of
  PR signal.

---

## Block A — Adapter Protocol + IndicatorValue / SourceRef contracts (Tasks 1–5)

### Task 1: `IndicatorValue` Pydantic + `SourceRef` Pydantic

**Files:**
- Create: `server/soundings/contracts/__init__.py`
- Create: `server/soundings/contracts/indicator_value.py`
- Create: `server/soundings/contracts/source_ref.py`
- Create: `server/tests/test_contracts.py`

`IndicatorValue` matches design §3 / §4 / spec §4.3:
`place_id, indicator, value (number|null), unit, period, source: SourceRef,
methodology_note: str|None, caveats: list[str], confidence:
Literal["official","modelled","experimental"]`.

`SourceRef` matches spec §7 exactly: `source_id, source_label, publisher,
publisher_url, dataset_url, retrieved_at, cache_status, licence`. JSON-serialisable.

Test: round-trip a sample of each through `model_dump_json()` → `model_validate_json()`, assert equality, assert ISO 8601 datetimes survive.

Commit: `feat(contracts): add IndicatorValue and SourceRef pydantic models`.

### Task 2: `SourceAdapter` Protocol (the contract)

**Files:**
- Create: `server/soundings/adapters/protocol.py`

Per design §3:

```python
class SourceAdapter(Protocol):
    source_id: str
    mode: Literal["loader", "passthrough"]

    async def fetch_indicator(
        self, indicator_key: str, place_id: str, period: str | None
    ) -> IndicatorValue | None: ...
    async def list_available_indicators(self) -> list[str]: ...
    def get_source_ref(
        self, *, retrieved_at: datetime, cache_status: Literal["live","cached","stale"]
    ) -> SourceRef: ...
```

No test — protocol is structural. Commit: `feat(adapters): SourceAdapter protocol`.

### Task 3: `LoaderAdapter` base extension — default `fetch_indicator` reads `data.indicator_value`

**Files:**
- Modify: `server/soundings/adapters/base.py`
- Create: `server/tests/test_loader_adapter_fetch.py`

Add a default `fetch_indicator` implementation on `LoaderAdapter` that reads
`(place_id, indicator_key, period_or_latest)` from `data.indicator_value`,
joins `data.loader_run` to derive `cache_status` ("cached" if within
`refresh_cadence`, "stale" if older than 1.5× cadence), and constructs the
`SourceRef` via the source row in `catalogue.source`. Subclasses can still
override.

Test (integration): seed one row in `data.indicator_value` plus a recent
`loader_run`; `fetch_indicator` returns the value with `cache_status="cached"`.
Then advance `loader_run.finished_at` past 1.5×; expect `cache_status="stale"`.

Commit: `feat(adapters): LoaderAdapter default fetch_indicator from data.indicator_value`.

### Task 4: `PassthroughAdapter` extension — wire `fetch_indicator` through `_fetch_cached`

**Files:**
- Modify: `server/soundings/adapters/passthrough_base.py`
- Create: `server/tests/test_passthrough_adapter_fetch.py`

`fetch_indicator` becomes a thin wrapper around `_fetch_cached(<cache_key
derived from indicator_key + place_id + period>)`. Subclasses still
implement `_call_upstream`; the new piece is the response → `IndicatorValue`
mapping which subclasses provide via a new abstract `_materialise(payload,
indicator_key, place_id, period) -> IndicatorValue | None`.

Test: a `FakePassthroughAdapter` implementation; on first call upstream
returns payload → IndicatorValue is produced with `cache_status="live"`;
second call within TTL → `cache_status="cached"`.

Commit: `feat(adapters): PassthroughAdapter.fetch_indicator with cache_status propagation`.

### Task 5: `SourceRef` factory keyed off `catalogue.source` rows

**Files:**
- Create: `server/soundings/adapters/source_ref_factory.py`
- Create: `server/tests/test_source_ref_factory.py`

`SourceRefFactory(engine).build(source_id, retrieved_at, cache_status)`
reads the catalogue row and emits a fully-populated `SourceRef`. Used by
both base classes — no copy-pasted strings in adapters.

Test: insert a row in `catalogue.source`, call factory, assert all
`SourceRef` fields populated correctly.

Commit: `feat(adapters): SourceRef factory backed by catalogue.source`.

---

## Block B — Nomis client + ons.mid_year_estimates + ons.census2021 (Tasks 6–15)

Both adapters share the same Nomis API. Build the shared client first, then
two thin adapters on top.

### Task 6: `NomisClient` — async HTTP wrapper with rate limiting

**Files:**
- Create: `server/soundings/adapters/nomis/__init__.py`
- Create: `server/soundings/adapters/nomis/client.py`
- Create: `server/tests/test_nomis_client.py`

Wraps `https://www.nomisweb.co.uk/api/v01/dataset/<dataset>.data.json?...`.
Methods: `get_observations(dataset_id, geography, measures, time)` returns
the parsed JSON. Rate-limited to 2 RPS via `aiolimiter`. Optional
`Authorization` header if `NOMIS_API_KEY` is set in env.

Test: mock response via `httpx.MockTransport`, assert correct URL parameters
and body parsing.

Commit: `feat(adapters): Nomis async client with rate limiting`.

### Task 7: Pin Nomis dataset/measure mapping per indicator key

**Files:**
- Create: `catalogue/nomis-mapping.yaml`
- Create: `server/soundings/adapters/nomis/mapping.py`
- Create: `server/tests/test_nomis_mapping.py`

Map each `population.*` and Census-sourced indicator key to:
`(dataset_id, measure_code, base_period_attr)`. Examples (verify live):

```yaml
- key: population.total
  source_id: ons.mid_year_estimates
  dataset_id: NM_2010_1
  measures: ["20100"]   # all-persons
  cell: ""              # not needed for MYE

- key: population.households.lone_parent_share
  source_id: ons.census2021
  dataset_id: NM_2021CT_173
  measures: ["20100"]
  cell: "L173_2"        # placeholder; pick real cell at first run
```

Test: yaml loads via pydantic; every mapping references an indicator key
that exists in `indicators.yaml`.

Commit: `feat(catalogue): nomis-mapping.yaml + pydantic loader`.

### Task 8: `ons.mid_year_estimates` loader

**Files:**
- Create: `server/soundings/adapters/ons_mid_year_estimates/__init__.py`
- Create: `server/soundings/adapters/ons_mid_year_estimates/loader.py`
- Create: `server/tests/test_mye_loader.py`
- Create: `server/tests/fixtures/nomis/mye_population_total_lsoa.json`

Loader iterates the four `population.*` mid-year-estimate keys, calls
`NomisClient.get_observations` per key for each supported geography level
(`lsoa21`, `msoa21`, `ltla24`, `utla24`, `region`, `country`), upserts into
`data.indicator_value`. One `loader_run` per source per invocation.

Test: cassette-style fixture (raw Nomis JSON), mocked `NomisClient`
response, assert ~10 rows land in `data.indicator_value` with correct
`indicator_key`, `place_id`, `value`, `period`.

Commit: `feat(adapters): ons.mid_year_estimates loader`.

### Task 9: `ons.mid_year_estimates` adapter shell

**Files:**
- Create: `server/soundings/adapters/ons_mid_year_estimates/adapter.py`
- Create: `server/tests/test_mye_adapter.py`

Inherits `LoaderAdapter`. `source_id = "ons.mid_year_estimates"`. Wires
`load()` to the Task-8 loader and inherits the default `fetch_indicator`
from Block A.

Test: integration — seed `data.indicator_value` directly, `fetch_indicator`
returns the row.

Commit: `feat(adapters): ons.mid_year_estimates adapter`.

### Task 10: `ons.mid_year_estimates` live test

**Files:**
- Create: `server/tests/live/test_mye_live.py`

Marked `@pytest.mark.live`. Runs the full loader against the real Nomis API
for a single LSOA + LTLA, asserts at least one indicator returns a numeric
value within plausible bounds.

Commit: `test(live): ons.mid_year_estimates against real Nomis API`.

### Task 11: `ons.census2021` loader

**Files:**
- Create: `server/soundings/adapters/ons_census2021/__init__.py`
- Create: `server/soundings/adapters/ons_census2021/loader.py`
- Create: `server/tests/test_census_loader.py`
- Create: `server/tests/fixtures/nomis/census_ethnicity_lsoa.json`

Same shape as Task 8 but iterates the seven `ons.census2021` indicators.
Census table cell selection is the only Census-specific bit; everything
else is shared with MYE via `NomisClient`.

Test: fixture-driven, asserts upserts.

Commit: `feat(adapters): ons.census2021 loader`.

### Task 12: `ons.census2021` adapter shell

**Files:**
- Create: `server/soundings/adapters/ons_census2021/adapter.py`
- Create: `server/tests/test_census_adapter.py`

Mirror of Task 9 but with `source_id = "ons.census2021"`.

Commit: `feat(adapters): ons.census2021 adapter`.

### Task 13: Census 2021 special-case — Welsh + English coverage and the Scotland gap

**Files:**
- Modify: `server/soundings/adapters/ons_census2021/loader.py`
- Modify: `catalogue/indicators.yaml` (caveats only — no contract change)
- Modify: `server/tests/test_census_loader.py`

Census 2021 covers England + Wales. Scotland was a separate exercise (NRS
2022); Northern Ireland had Census 2021. The loader silently skips
geographies it doesn't have data for (Scotland in particular) and the
indicator catalogue gets a uniform "England + Wales only at LSOA/MSOA"
caveat.

Test: feed a Scottish LSOA into the loader; assert no row is written and no
exception is raised.

Commit: `feat(adapters): ons.census2021 — document E+W coverage gap`.

### Task 14: Census + MYE live tests

**Files:**
- Create: `server/tests/live/test_census_live.py`

Live coverage as Task 10 but for Census.

Commit: `test(live): ons.census2021 against real Nomis API`.

### Task 15: Wire MYE + Census loaders into `make seed-light`

**Files:**
- Modify: `server/soundings/seed/run.py`

Append the new loaders after the geography spine. `--light` runs them for
the single LTLA Stockton-on-Tees and its descendant geographies; `--full`
runs them everywhere.

No test (CLI smoke covered by Phase 0 task 36 tests). Commit: `feat(seed): include MYE + Census loaders in make seed-light`.

---

## Block C — mhclg.imd2025 adapter (Tasks 16–21)

### Task 16: Pin IMD bulk-download URL + sheet/column mapping

**Files:**
- Create: `docs/adr/0002-imd2025-data-source.md`
- Create: `catalogue/imd2025-mapping.yaml`

ADR pins the gov.uk download URL for the IMD 2025 spreadsheet (or whichever
file format MHCLG actually publishes — verify) and the sheet name + column
mapping per indicator key (`deprivation.imd.score`, `deprivation.imd.decile`,
the four domain scores, IDACI, IDAOPI). Same URL-stale-fix pattern as ADR-0001.

No test. Commit: `docs: ADR-0002 IMD 2025 data source`.

### Task 17: IMD spreadsheet parser

**Files:**
- Create: `server/soundings/adapters/mhclg_imd2025/__init__.py`
- Create: `server/soundings/adapters/mhclg_imd2025/parser.py`
- Create: `server/tests/test_imd_parser.py`
- Create: `server/tests/fixtures/imd/imd2025_sample.xlsx`

Pure function `parse_imd_xlsx(blob: bytes) -> list[ImdRow]` where `ImdRow`
is `(lsoa_code, indicator_key, value)`. Uses `openpyxl`. Fixture is a hand-
crafted ~10-row xlsx covering a known cluster of LSOAs.

Test: parse fixture, assert all expected rows + values.

Commit: `feat(adapters): mhclg.imd2025 spreadsheet parser`.

### Task 18: IMD loader

**Files:**
- Create: `server/soundings/adapters/mhclg_imd2025/loader.py`
- Create: `server/tests/test_imd_loader.py`

Downloads the IMD xlsx via `httpx`, parses via Task 17, upserts into
`data.indicator_value` with `period = "2025"`. One `loader_run` row.

Test: mock the HTTP download, parse the fixture, assert rows land.

Commit: `feat(adapters): mhclg.imd2025 loader`.

### Task 19: IMD LSOA → LTLA aggregation

**Files:**
- Create: `server/soundings/adapters/mhclg_imd2025/aggregation.py`
- Create: `server/tests/test_imd_aggregation.py`

LTLA-level IMD is the population-weighted average of LSOA scores. Reads
LSOA values and a per-LSOA population (from `ons.mid_year_estimates` —
hence the dependency order in `make seed`), writes LTLA rows back to
`data.indicator_value` with the same `period`.

Test: seed two LSOAs in one fake LTLA with known populations + scores,
assert weighted average lands.

Commit: `feat(adapters): mhclg.imd2025 LSOA → LTLA aggregation`.

### Task 20: IMD adapter shell + live test

**Files:**
- Create: `server/soundings/adapters/mhclg_imd2025/adapter.py`
- Create: `server/tests/test_imd_adapter.py`
- Create: `server/tests/live/test_imd_live.py`

Standard `LoaderAdapter` shell. Live test asserts a known LSOA returns a
score in plausible range.

Commit: `feat(adapters): mhclg.imd2025 adapter + live test`.

### Task 21: Wire IMD loader into `make seed-light`

**Files:**
- Modify: `server/soundings/seed/run.py`

Runs after MYE (since aggregation needs population). `--light` filters to
descendants of the dev LTLA.

Commit: `feat(seed): include IMD loader in make seed-light, after MYE`.

---

## Block D — IndicatorOrchestrator (Tasks 22–26)

### Task 22: `AdapterRegistry`

**Files:**
- Create: `server/soundings/orchestration/__init__.py`
- Create: `server/soundings/orchestration/registry.py`
- Create: `server/tests/test_adapter_registry.py`

Reads `catalogue.source` + the indicator catalogue, returns the right
adapter instance for a given indicator key. Lazy-construct adapters on
demand. Adapters are configured via a small declarative registration
(`AdapterRegistry.register(source_id, factory)`), wired in `app.py`'s
lifespan.

Test: register two fake adapters, look up by indicator → returns expected
instance; unknown indicator → raises `IndicatorNotRegisteredError`.

Commit: `feat(orchestration): AdapterRegistry`.

### Task 23: `IndicatorOrchestrator.fetch` — concurrent fan-out

**Files:**
- Create: `server/soundings/orchestration/orchestrator.py`
- Create: `server/tests/test_orchestrator.py`

```python
async def fetch(
    self,
    indicator_keys: list[str],
    place_id: str,
    period: str | None,
    *,
    timeout: float = 10.0,
) -> OrchestrationResult: ...
```

Per design §4: `asyncio.gather(return_exceptions=True)`, soft 10s budget,
returns `OrchestrationResult(values: list[IndicatorValue], caveats:
list[str], partial: bool)`. SourceRef dedup `(source_id,
retrieved_at_minute)`.

Test: two stub adapters, one happy + one that raises; result has 1 value, 1
caveat, `partial=True`.

Commit: `feat(orchestration): concurrent fan-out with failure isolation`.

### Task 24: `INDICATOR_NOT_AVAILABLE_AT_LEVEL` enforcement

**Files:**
- Modify: `server/soundings/orchestration/orchestrator.py`
- Create: `server/soundings/orchestration/errors.py`
- Create: `server/tests/test_orchestrator_levels.py`

If the requested place_id's `type` is not in the indicator's `available_at`,
the orchestrator does not call the adapter and emits an
`INDICATOR_NOT_AVAILABLE_AT_LEVEL` error in the result. No silent
approximation.

Test: ask for `population.households.lone_parent_share` at `country:E92000001`
(census table not published at country); expect explicit error, not a value.

Commit: `feat(orchestration): refuse rather than approximate when level unsupported`.

### Task 25: SourceRef deduplication

**Files:**
- Modify: `server/soundings/orchestration/orchestrator.py`
- Modify: `server/tests/test_orchestrator.py`

Dedup key: `(source_id, retrieved_at.replace(second=0,microsecond=0))`.
Returned alongside values so the UI can render a single citation.

Commit: `refactor(orchestration): dedupe SourceRef per (source_id, minute)`.

### Task 26: Orchestrator wiring in app lifespan

**Files:**
- Modify: `server/soundings/app.py`
- Create: `server/tests/test_orchestrator_lifespan.py`

In the FastAPI lifespan, build the `AdapterRegistry`, pass to
`IndicatorOrchestrator`, store on `app.state.orchestrator`. Tests assert
the singleton is reachable from a route.

Commit: `feat(app): wire orchestrator into FastAPI lifespan`.

---

## Block E — `find_place` tool (Tasks 27–29)

### Task 27: `find_place` input/output models + handler

**Files:**
- Create: `server/soundings/tools/__init__.py`
- Create: `server/soundings/tools/find_place.py`
- Create: `server/tests/test_tool_find_place.py`

Input/output pydantic models match spec §4.1. Handler delegates to
`GeographyService.find_place_by_postcode` if the input parses as a UK
postcode (regex), else `find_place_by_name`. Hierarchy depth kicks
ranking: prefer `country < region < utla24 < ltla24 < msoa21 < lsoa21` for
ties on similarity score.

Test: postcode input → returns `lsoa21:...` etc.; name input → returns
ranked match list with `confidence`.

Commit: `feat(tools): find_place handler`.

### Task 28: Confidence ranking tests against catalogue place data

**Files:**
- Modify: `server/tests/test_tool_find_place.py`

Seed multiple places named "Newcastle" (city, county, area). Search
"Newcastle" → top match is the LTLA, confidence > 0.8.

Commit: `test(tools): find_place ranking by name + hierarchy depth`.

### Task 29: `find_place` JSON schema dump for `/v1/tools` listing

**Files:**
- Modify: `server/soundings/tools/find_place.py`

Add `find_place.tool_spec()` returning a dict with `name`, `description`,
`input_schema`, `output_schema` derived from the pydantic models. Used by
both the HTTP `/v1/tools` listing and MCP registration.

Commit: `feat(tools): find_place tool_spec for transport-agnostic registration`.

---

## Block F — `get_indicators` tool (Tasks 30–33)

### Task 30: `get_indicators` input/output models + handler

**Files:**
- Create: `server/soundings/tools/get_indicators.py`
- Create: `server/tests/test_tool_get_indicators.py`

Input matches spec §4.3. Handler calls
`IndicatorOrchestrator.fetch(indicator_keys=indicators, place_id, period)`,
maps to output. Format defaults to `wide` (one row per place) with `tall`
the alternative.

Test: seed two indicators in `data.indicator_value`, call handler, assert
both come back with correct shape.

Commit: `feat(tools): get_indicators handler`.

### Task 31: Wide vs tall format post-shape

**Files:**
- Modify: `server/soundings/tools/get_indicators.py`
- Modify: `server/tests/test_tool_get_indicators.py`

Wide groups by `place_id` with one column per indicator; tall is the
flat list per spec §4.3. Both share the deduplicated `SourceRef[]`.

Commit: `feat(tools): get_indicators wide/tall formats`.

### Task 32: caveats from indicator catalogue + adapter response

**Files:**
- Modify: `server/soundings/tools/get_indicators.py`
- Modify: `server/tests/test_tool_get_indicators.py`

The handler concatenates `indicator.caveats` (from the catalogue) with the
per-call caveats the orchestrator collected (rate limits, partial failures).

Commit: `feat(tools): get_indicators surfaces both static + dynamic caveats`.

### Task 33: `get_indicators` tool_spec + JSON schema dump

**Files:**
- Modify: `server/soundings/tools/get_indicators.py`

Same pattern as Task 29. Commit: `feat(tools): get_indicators tool_spec`.

---

## Block G — `get_place_profile` tool (Tasks 34–37)

### Task 34: `get_place_profile` input/output + domain → indicator-keys lookup

**Files:**
- Create: `server/soundings/tools/get_place_profile.py`
- Create: `server/tests/test_tool_get_place_profile.py`

Input per spec §4.2. Handler resolves `include` domains
("population", "deprivation", "economy", …) to the matching indicator
keys via the catalogue (`indicator.key.split(".")[0]`-prefixed match), then
fans out via the orchestrator.

Test: include `["population"]` against a Stockton LTLA seeded with two
indicators; expect both back with correct domain.

Commit: `feat(tools): get_place_profile domain dispatch`.

### Task 35: Per-domain failure → `caveats`

**Files:**
- Modify: `server/soundings/tools/get_place_profile.py`
- Modify: `server/tests/test_tool_get_place_profile.py`

Failures in one domain don't fail the whole call. The failed domain
appears as a `caveats` entry naming the failed source.

Commit: `feat(tools): get_place_profile per-domain failure isolation`.

### Task 36: `confidence` field — official/modelled/experimental

**Files:**
- Modify: `server/soundings/tools/get_place_profile.py`
- Modify: `catalogue/indicators.yaml` — add `confidence` to each entry

Per spec §4.2: every `IndicatorValue` carries a `confidence` flag. Default
"official"; loader-mode adapters can override per indicator. v1 reserves
"experiential" for v3.

Test: assert returned profile has `confidence` populated everywhere.

Commit: `feat(tools): get_place_profile confidence field`.

### Task 37: `get_place_profile` tool_spec

**Files:**
- Modify: `server/soundings/tools/get_place_profile.py`

Commit: `feat(tools): get_place_profile tool_spec`.

---

## Block H — Transports (HTTP + MCP) (Tasks 38–44)

### Task 38: HTTP routes for the three tools

**Files:**
- Create: `server/soundings/http/tools.py`
- Modify: `server/soundings/app.py`
- Create: `server/tests/test_http_tool_routes.py`

`POST /v1/tools/find_place`, `POST /v1/tools/get_place_profile`,
`POST /v1/tools/get_indicators`. Body validates against the input pydantic;
response is the output pydantic (wrapped).

Test: integration via httpx ASGI client; assert 200 + correct shape per
tool, 422 on invalid input.

Commit: `feat(http): /v1/tools/{find_place,get_place_profile,get_indicators}`.

### Task 39: `GET /v1/tools` listing

**Files:**
- Modify: `server/soundings/http/tools.py`
- Modify: `server/tests/test_http_tool_routes.py`

Returns a list of tool_specs from each tool module.

Commit: `feat(http): GET /v1/tools listing with input/output schemas`.

### Task 40: Error envelope middleware

**Files:**
- Create: `server/soundings/http/errors.py`
- Modify: `server/soundings/app.py`
- Create: `server/tests/test_http_errors.py`

Wraps all `/v1/*` responses in the design §4 error envelope on exception:
`{"error": {"code", "message", "details"}}`. Codes mapped from Python
exception types (e.g. `IndicatorNotAvailableAtLevelError` →
`INDICATOR_NOT_AVAILABLE_AT_LEVEL`).

Test: simulate each error code, assert envelope shape + status code (4xx
for client errors, 502 for upstream timeouts, 500 for INTERNAL).

Commit: `feat(http): error envelope middleware per design §4`.

### Task 41: `GET /v1/sources`

**Files:**
- Create: `server/soundings/http/sources.py`
- Modify: `server/soundings/app.py`
- Create: `server/tests/test_http_sources.py`

Reads `catalogue.source` + `data.loader_run` (latest per source) and
returns a JSON listing per design §4. No auth.

Commit: `feat(http): GET /v1/sources with last loader_run per source`.

### Task 42: `GET /v1/catalogue/indicators`

**Files:**
- Create: `server/soundings/http/catalogue.py`
- Modify: `server/soundings/app.py`
- Create: `server/tests/test_http_catalogue.py`

Returns the full indicator catalogue as JSON (read from Postgres for
freshness, not from yaml, to honour the catalogue_version stamp).

Commit: `feat(http): GET /v1/catalogue/indicators`.

### Task 43: Mount MCP server at `/mcp` over SSE

**Files:**
- Create: `server/soundings/mcp/__init__.py`
- Create: `server/soundings/mcp/server.py`
- Modify: `server/soundings/app.py`
- Create: `server/tests/test_mcp_transport.py`

Use the `mcp` Python SDK's lowlevel server with SSE transport, mount on the
existing FastAPI app at `/mcp`. Register the three tools using the
tool_specs from Blocks E/F/G. Single implementation, two transports.

Test: spin up the ASGI app, open an SSE session, list tools, call
`find_place` for a postcode, assert response.

Commit: `feat(mcp): MCP server mounted at /mcp with three tools`.

### Task 44: Lock CORS to UI origin

**Files:**
- Modify: `server/soundings/app.py`
- Modify: `server/soundings/core/config.py`

Add `SOUNDINGS_UI_ORIGIN` env var (default `http://localhost:8088`). FastAPI
`CORSMiddleware` with `allow_origins=[settings.ui_origin]` for `/v1/*` and
`/mcp/*`.

Commit: `chore(http): lock CORS to configured UI origin`.

---

## Block I — Loader daemon + ops endpoints (Tasks 45–49)

### Task 45: `loader` Docker service

**Files:**
- Modify: `infra/docker-compose.yml`

Adds a new service `loader` using the same image as `server` (no separate
build), running `python -m soundings.loader.run`. No exposed ports.
Restart `unless-stopped`. depends_on `postgres` healthy.

Commit: `chore(infra): add loader docker service`.

### Task 46: APScheduler-driven loader daemon

**Files:**
- Create: `server/soundings/loader/__init__.py`
- Create: `server/soundings/loader/run.py`
- Create: `server/tests/test_loader_daemon.py`

Reads `catalogue.source` rows (mode='loader'), schedules each on its
`refresh_cadence` cron string via APScheduler's `AsyncIOScheduler`. Each
fire kicks off the source's loader and writes a `loader_run` row. Manual
`--once <source_id>` flag for ops.

Test: APScheduler config built correctly from source rows; assert four
sources scheduled.

Commit: `feat(loader): APScheduler daemon driven by catalogue.source.refresh_cadence`.

### Task 47: Per-source loader registry + `--once` invocation

**Files:**
- Modify: `server/soundings/loader/run.py`
- Modify: `server/tests/test_loader_daemon.py`

A small registry maps `source_id` → loader function (the four
`ons.geography` loaders, MYE, Census, IMD). Daemon invokes via this map.
`--once ons.census2021` runs Census loader synchronously and exits — used
for ops debugging.

Commit: `feat(loader): per-source registry + --once flag`.

### Task 48: `/healthz` reflects last successful loader run

**Files:**
- Modify: `server/soundings/http/health.py`
- Modify: `server/tests/test_healthz.py`

Adds a `loader_runs` check that summarises the latest `loader_run.finished_at`
per source. A source whose latest run is older than `1.5 × refresh_cadence`
flips healthz to "degraded" with a per-source detail.

Commit: `feat(http): /healthz reports stale loader runs`.

### Task 49: Loader retry policy on transient failure

**Files:**
- Modify: `server/soundings/loader/run.py`
- Create: `server/tests/test_loader_retry.py`

Exponential backoff (1s/4s/16s) on connection errors and 5xx. No retry on
4xx. Three attempts max.

Commit: `feat(loader): exponential retry on transient upstream failures`.

---

## Block J — Integration + tag (Tasks 50–52)

### Task 50: Phase 1 e2e test — get_indicators over HTTP

**Files:**
- Create: `server/tests/test_phase_1_e2e.py`

Seeds catalogue, MYE+Census+IMD rows directly into `data.indicator_value`
(no real loader call), then `POST /v1/tools/get_indicators` with
`["population.total","deprivation.imd.score"]` for `ltla24:E06000004`. Asserts
both come back with valid `SourceRef[]` and `cache_status` populated.

Commit: `test: phase 1 e2e — get_indicators via HTTP`.

### Task 51: Phase 1 e2e test — same call over MCP

**Files:**
- Modify: `server/tests/test_phase_1_e2e.py`

Same logical flow as Task 50 but through the MCP transport at `/mcp`. Uses
the `mcp` SDK's test client. Asserts both transports return the same
indicator values for the same input.

Commit: `test: phase 1 e2e — get_indicators via MCP transport`.

### Task 52: Tag `v0.2.0-phase-1`

**Steps:**
1. `make lint && make type && make test && make test-integration` all green.
2. `make up && make migrate && make seed-light` runs the new MYE+Census+IMD
   loaders successfully.
3. Update `STATE.md` and `PLAN.md` (Phase 1 done, Phase 2 next).
4. Tag and push:

```bash
git tag -a v0.2.0-phase-1 -m "phase 1: indicator pipeline + 3 tools, HTTP + MCP"
git push origin v0.2.0-phase-1
```

Commit: `docs: phase 1 complete — indicator pipeline live`.

---

## Done criteria for Phase 1

All green simultaneously:

- [ ] `make seed-light` runs ons.mid_year_estimates + ons.census2021 +
      mhclg.imd2025 loaders successfully and seeds `data.indicator_value`.
- [ ] `cd server && uv run pytest -m "not live"` passes.
- [ ] `cd server && uv run pytest -m integration` passes against the running
      stack.
- [ ] `cd server && uv run pytest -m live` passes nightly (allowed flake on
      transient upstream failures, but not three nights in a row).
- [ ] `POST /v1/tools/get_indicators` for a Stockton LTLA returns
      `population.total` (MYE), `population.households.lone_parent_share`
      (Census), and `deprivation.imd.score` (IMD) with `cache_status` set
      and de-duplicated `SourceRef[]`.
- [ ] An MCP client connecting to `/mcp` lists three tools and gets the
      same answer to the same input.
- [ ] `GET /v1/sources` shows `finished_at` for every loader source.
- [ ] `loader` Docker service comes up green and APScheduler logs show
      four cron jobs scheduled.
- [ ] CI on `main` is green (PR job + nightly job).
- [ ] Tag `v0.2.0-phase-1` pushed.

---

## What's next (preview, not in this plan)

**Phase 2** — Capture pipeline (raw_record + sanitised question_record),
two-step write, NER + small-org redaction, monthly publication job. Pulls
in the minimal `/` and `/place/{id}` UI per spec §9. To be planned as
`docs/plans/<date>-soundings-v1-phase-2-plan.md` once Phase 1 is shipped.

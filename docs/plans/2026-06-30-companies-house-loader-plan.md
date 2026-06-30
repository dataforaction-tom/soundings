# Companies House Loader — Implementation Plan

**Date:** 2026-06-30
**Status:** Shipped (aggregates-only). SIC/category mix deferred; NSPL pre-warm deferred.
**Parent:** PLAN.md — Phase 6b (breadth, NDL data-source expansion)
**Track:** First Phase 6b source. New domain depth: **Economy**.

## Objective

Add **active companies per place** indicators to Soundings, sourced from
Companies House. Aggregates-only: store per-LTLA indicator values, **not**
per-company rows.

## Why a loader (bulk carve-out), not passthrough

Research (2026-06-30) verified the Companies House REST API **cannot** serve
our access pattern:

- The only geographic control on `/advanced-search/companies` is a **fuzzy
  free-text `location`** field (post-town/locality/postcode text). There is no
  postcode, region, county, or LTLA parameter, and postcode matching is fuzzy
  (CH staff confirm you can't reliably scope to a postcode).
- Rate limit is 600 req / 5 min, killing any "enumerate every postcode in an
  LTLA" workaround (an LTLA holds thousands of postcodes).

Both carve-out conditions from the Phase 4 architecture decision are met:
(a) no discovery endpoint supports our access pattern, and (b) monthly cadence.
**This is the same carve-out we accepted for the Charity Commission.** The
loader reuses the CC machinery almost wholesale.

Source of truth: Free Company Data Product — monthly CSV (in ZIP), ~5M live
companies, includes `RegAddress.PostCode`, `CompanyStatus`, `CompanyCategory`,
`IncorporationDate`, and SIC codes.
URL: `https://download.companieshouse.gov.uk/en_output.html`

## Architecture decisions

| Decision | Rationale |
|---|---|
| **Aggregates-only** (no `data.organisation` rows) | We only need per-LTLA counts. Streaming-aggregate keeps storage to a handful of indicator-value rows and avoids mirroring ~5M companies locally — honours "cache, don't mirror". A future "businesses in place" drill-down could add rows later, out of scope here. |
| **LTLA granularity only** (v1) | Postcode→LTLA is the clean, meaningful unit for business counts. Postcode→LSOA exists in `geography.postcode` but company counts per LSOA are noisy; defer. |
| **Stream + accumulate, don't list** | CC holds all 220k rows in memory (~50MB). At 5M rows that's ~1–1.5GB — too much. Instead stream the CSV and accumulate `dict[normalised_postcode → counts]`; memory is bounded by the distinct-postcode set (~hundreds of MB worst case). |
| **Reuse `resolve_postcodes_to_ltlas` + `bulk_upsert`** | Same postcode→LTLA bridge as CC. `geography.postcode` is the durable cache; monthly re-runs against a warm cache hit postcodes.io zero times. |
| Period = `YYYY-MM` (snapshot month), UPSERT on `(place_id, indicator_key, period)` | Matches CC. Re-running in the same calendar month overwrites. |

## Scale risk (the one real risk) + mitigation

First national run resolves the distinct active-company postcode set
(~1M+ postcodes) via postcodes.io bulk (100/POST) on a cold cache — ~10k+ calls
at rps 10 ≈ ~15–20 min. This is a **monthly background batch**, not user-facing,
so latency is acceptable; the cache warms permanently in `geography.postcode`,
making subsequent runs near-free.

- **Mitigation now:** in `make seed-light`, restrict ingestion to a single
  LTLA's postcodes (or skip the loader) so local smoke stays fast.
- **Recommended follow-up (out of scope):** pre-load ONS NSPL/ONSPD bulk once
  to fully populate `geography.postcode` — speeds up CH *and* every other
  postcode-based loader. Tracked as a separate task.

## Indicators (catalogue/indicators.yaml — new `economy` entries)

```yaml
- key: economy.active_companies_count
  label: "Active companies"
  description: "Count of companies on the live register with a registered office in the area."
  unit: "companies"
  higher_is: null
  source_id: "companies_house"
  available_at: ["ltla24", "utla24"]
  refresh_cadence: "monthly"
  caveats:
    - "Counted by registered-office postcode, which may differ from where a company trades."
    - "Live register only; dissolved companies are excluded from the free data product."

- key: economy.active_companies_per_1000
  label: "Active companies per 1,000 residents"
  description: "Active companies per 1,000 resident population (registered-office basis)."
  unit: "per 1,000 population"
  higher_is: null
  source_id: "companies_house"
  available_at: ["ltla24", "utla24"]
  refresh_cadence: "monthly"
  caveats:
    - "Registered-office basis; not a measure of business activity or employment."

- key: economy.new_incorporations_12m
  label: "New company incorporations (last 12 months)"
  description: "Companies incorporated in the 12 months to the snapshot date, by registered-office area."
  unit: "companies"
  higher_is: null
  source_id: "companies_house"
  available_at: ["ltla24", "utla24"]
  refresh_cadence: "monthly"
  caveats:
    - "Derived from IncorporationDate within the live-register snapshot; companies incorporated then dissolved within the window are not counted."
```

(Stretch, optional: `economy.company_category_mix` as composition data, and a
SIC top-sector indicator. Deferred unless wanted — keeps the first PR tight.)

## Source (catalogue/sources.yaml — new entry)

```yaml
- id: companies_house
  label: Companies House — Free Company Data Product
  publisher: Companies House
  publisher_url: https://www.gov.uk/government/organisations/companies-house
  dataset_url: https://download.companieshouse.gov.uk/en_output.html
  licence: OGL-UK-3.0
  mode: loader
  # CH publishes the bulk product within ~5 working days of month end.
  refresh_cadence: "0 5 7 * *"
  rate_limit: { rps: 4 }
```

## New files

```
server/soundings/adapters/companies_house/__init__.py
server/soundings/adapters/companies_house/client.py    # bulk ZIP download + streaming CSV reader
server/soundings/adapters/companies_house/loader.py    # CompaniesHouseLoader (aggregates-only)
server/tests/test_companies_house_client.py
server/tests/test_companies_house_loader.py
```

Reused as-is: `adapters/charity_commission/mapping.resolve_postcodes_to_ltlas`,
`adapters/postcodes_io/adapter.PostcodesIoAdapter`, `adapters/base.LoaderAdapter`.
(Consider lifting `resolve_postcodes_to_ltlas` to a shared `adapters/postcodes_io`
helper since a second consumer now exists — small refactor, flagged in Task 2.)

## TDD task breakdown

Each task: failing test → minimum implementation → green → conventional commit.

1. **Client — streaming CSV reader over the bulk ZIP.**
   `CompaniesHouseBulkClient.iter_active_companies()` yields dicts
   `{company_number, name, status, category, incorporation_date, postcode, sic_codes}`
   for `CompanyStatus == "Active"`. Test with a `MockTransport` serving a tiny
   in-memory ZIP of 2–3 CSV rows. Remember `csv.field_size_limit(16 * 1024 * 1024)`
   (CC lesson). Commit: `feat(companies-house): streaming bulk CSV client`.

2. **(Optional refactor) shared postcode resolver.** If lifting
   `resolve_postcodes_to_ltlas` out of `charity_commission`, do it test-first so
   both CC and CH import the shared location. Commit: `refactor: share postcode→LTLA resolver`.

3. **Loader — streaming aggregation.** `CompaniesHouseLoader.load()`:
   stream client → accumulate `dict[norm_postcode → {count, incorp_12m}]` →
   resolve distinct postcodes → roll up to LTLA → return counts. Unit-test the
   aggregation logic with a fake client + fake resolver (no DB). Commit:
   `feat(companies-house): streaming per-LTLA aggregation`.

4. **Loader — indicator UPSERT** (integration, test DB). Mirror CC's
   `_aggregate_indicators`: UPSERT `active_companies_count`,
   `active_companies_per_1000` (INNER JOIN latest `population.total`),
   `new_incorporations_12m` into `data.indicator_value`. Test against
   `soundings_test` seeding 1–2 LTLAs + a `population.total` row. Commit:
   `feat(companies-house): per-LTLA indicator aggregates`.

5. **Catalogue + registration.** Add the source + 3 indicators to the YAMLs;
   register `CompaniesHouseLoader` in `loader/run.py` `build_source_registry`;
   confirm `test_catalogue_loader` stays green (sources cover all indicator
   `source_id`s). Commit: `feat(companies-house): catalogue entries + loader registration`.

6. **Live test** (`@pytest.mark.live`). Fetch the real bulk product head /
   first N rows; assert the URL is alive and the parser handles the real schema
   (scope tight — first ~50k rows in seconds, per the CC live-test lesson; do
   NOT run a full 5M ingest in CI). Commit: `test(companies-house): live schema smoke`.

7. **Docs.** Update STATE.md component table + PLAN.md Phase 6b checklist; note
   the NSPL pre-warm follow-up. Commit: `docs: companies house loader shipped`.

## Out of scope

- Per-company storage / "businesses in this place" drill-down.
- LSOA-level company counts.
- SIC/category composition indicators (stretch, separate PR if wanted).
- ONS NSPL/ONSPD bulk pre-warm (separate, broadly-beneficial task).

## Verification

- `make test` (unit) + `make test-integration` (Task 4) green.
- mypy strict clean; pre-commit clean.
- Local smoke: seed-light path stays fast (single-LTLA restriction); a manual
  `python -m soundings.loader.run --once companies_house` against a warm
  postcode cache writes counts for seeded LTLAs.
```

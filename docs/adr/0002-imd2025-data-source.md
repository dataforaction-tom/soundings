# ADR-0002: IMD data sources (2025 + 2019)

**Status:** Accepted
**Date:** 2026-05-11 (updated; original 2026-05-10)
**Context:** Phase 1 — `mhclg.imd2025` adapter
(`docs/plans/2026-05-10-soundings-v1-phase-1-plan.md` Block C).
The original ADR assumed IMD 2025 was not yet published and documented a
fallback to 2019. IMD 2025 is now live, and we keep 2019 as a sibling source
rather than a fallback so callers can compare across editions.

## Decision

Two IMD source IDs live side by side:

- `mhclg.imd2025` — period `"2025"` — current edition
- `mhclg.imd2019` — period `"2019"` — previous edition

Both write identical indicator keys (`deprivation.imd.score`, `…decile`,
`…income_score`, etc.) to `data.indicator_value` with their own period
value. `fetch_indicator(period=None)` returns the latest period (2025).
Callers that want a specific edition pass `period="2019"`.

Same Python class hierarchy — `MhclgImd2019Loader` is a subclass of
`MhclgImd2025Loader` that overrides `source_id`, `default_url`, and
`period`. Parser is identical for both editions.

## Sources

| Aspect | 2025 | 2019 |
|---|---|---|
| Publisher | MHCLG | MHCLG |
| Dataset URL | <https://www.gov.uk/government/statistics/english-indices-of-deprivation-2025> | <https://www.gov.uk/government/statistics/english-indices-of-deprivation-2019> |
| Bulk file | `File_2_IoD2025_Domains_of_Deprivation.xlsx` | `File_2_-_IoD2019_Domains_of_Deprivation.xlsx` |
| Direct download URL | `https://assets.publishing.service.gov.uk/media/691decfae39a085bda43efcd/File_2_IoD2025_Domains_of_Deprivation.xlsx` | `https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/833970/File_2_-_IoD2019_Domains_of_Deprivation.xlsx` |
| Coverage | England | England |
| Geography | LSOA 2021 | LSOA 2011 |
| Licence | OGL-UK-3.0 | OGL-UK-3.0 |

## Sheet → indicator mapping

We read the LSOA-level sheet (typically the second tab) and pick columns by
header name. Header names are pinned here; if MHCLG renames a column we
update this table and the parser at the same time. The mapping below
applies to both editions — MHCLG kept the column names stable.

| Indicator key | Sheet | Column header (case-insensitive substring match) |
|---|---|---|
| `deprivation.imd.score` | LSOA | `Index of Multiple Deprivation (IMD) Score` |
| `deprivation.imd.decile` | LSOA | `Index of Multiple Deprivation (IMD) Decile` |
| `deprivation.imd.income_score` | LSOA | `Income Score (rate)` |
| `deprivation.imd.employment_score` | LSOA | `Employment Score (rate)` |
| `deprivation.imd.health_score` | LSOA | `Health Deprivation and Disability Score` |
| `deprivation.imd.education_score` | LSOA | `Education, Skills and Training Score` |
| `deprivation.idaci` | LSOA | `Income Deprivation Affecting Children Index (IDACI) Score (rate)` |
| `deprivation.idaopi` | LSOA | `Income Deprivation Affecting Older People (IDAOPI) Score (rate)` |

LSOA → LTLA aggregation: population-weighted average using ONS Mid-Year
Estimates (the loaders run after MYE so the populations are already in
`data.indicator_value`). The aggregation function takes a `source_id`
parameter and is invoked once per IMD edition.

## LSOA boundary versions

IMD 2025 uses LSOA 2021 codes; IMD 2019 uses LSOA 2011 codes. Most LSOAs
are stable across editions but some were split/merged in the 2011→2021
change. We write all rows under `place_id = "lsoa21:<code>"` for layout
consistency. Rows whose code only existed in 2011 will not have a matching
`geography.place_hierarchy` parent and therefore won't roll up into LTLA
aggregation. That's an accepted small accuracy loss for the 2019 LTLA
rollup — exact mapping via LSOA 2011→2021 change tables is deferred to a
later phase if a use case demands it.

## Refresh cadence

IMD is recomputed on a multi-year cadence (2010, 2015, 2019, 2025).
Between cadences each loader still runs (2025 monthly, 2019 yearly) per
the `refresh_cadence` cron in `sources.yaml` so a republished or revised
edition gets picked up promptly.

## What changes if a file location moves

1. Update the row in this ADR.
2. Update the `*_BULK_URL` constant in
   `server/soundings/adapters/mhclg_imd2025/loader.py`.
3. Re-run `make seed-light`.

The loader is idempotent — re-running replaces rows wholesale on the
unique key `(place_id, indicator_key, period)`.

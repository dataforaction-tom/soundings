# ADR-0002: IMD 2025 data source

**Status:** Accepted
**Date:** 2026-05-10
**Context:** Phase 1 — `mhclg.imd2025` adapter
(`docs/plans/2026-05-10-soundings-v1-phase-1-plan.md` Block C).

## Decision

The IMD 2025 adapter consumes MHCLG's published Excel workbook directly.
Same pattern as ADR-0001: pin the URL + sheet + column layout here so a
download going stale becomes a single-file fix.

## Source

| Aspect | Value |
|---|---|
| Publisher | Ministry of Housing, Communities and Local Government |
| Dataset URL | <https://www.gov.uk/government/statistics/english-indices-of-deprivation-2025> |
| Bulk file | `File_2_-_IoD2025_Domains_of_Deprivation.xlsx` *(unverified — confirm at first run)* |
| Direct download URL | `https://assets.publishing.service.gov.uk/.../IoD2025_File_2_Domains_of_Deprivation.xlsx` *(unverified)* |
| Coverage | England only (Wales, Scotland, NI publish separately) |
| Geography | LSOA 2021 (with LTLA aggregations supplied) |
| Licence | OGL-UK-3.0 |

## Sheet → indicator mapping

We read the LSOA-level sheet (typically the second tab) and pick columns by
header name. Header names are pinned here; if MHCLG renames a column we
update this table and the loader at the same time.

| Indicator key | Sheet | Column header (case-insensitive) |
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
Estimates (the loader runs after MYE so the populations are already in
`data.indicator_value`).

## Fallback if 2025 isn't published yet

If `File_2_*.xlsx` 404s at first run, fall back to IMD 2019 at:
`https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/833970/File_2_-_IoD2019_Domains_of_Deprivation.xlsx`.
Update sources.yaml + this ADR to swap `mhclg.imd2025` → `mhclg.imd2019`
in lockstep; the indicator catalogue keeps the same keys.

## Refresh cadence

IMD is recomputed on a multi-year cadence (2010, 2015, 2019, 2025).
Between cadences the loader still runs monthly per the design (via the
`refresh_cadence` cron in `sources.yaml`) so a republished or revised
edition gets picked up promptly.

## What changes if the file location moves

1. Update the row in this ADR.
2. Update the URL constant in `server/soundings/adapters/mhclg_imd2025/loader.py`.
3. Re-run `make seed-light`.

The loader is idempotent — re-running replaces the IMD rows wholesale.

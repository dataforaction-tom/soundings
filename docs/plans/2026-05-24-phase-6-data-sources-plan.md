# Phase 6 Data Sources Plan

**Date:** 2026-05-24
**Status:** Draft (URL validation complete)
**Parent:** PLAN.md — Phase 6

## Validation Status

| Source | Status | Verified URL |
|--------|--------|--------------|
| Ofcom Connected Nations | ⚠️ Redirects | `https://www.ofcom.org.uk/research-and-data` |
| Ofsted | ⚠️ Changed | `https://www.gov.uk/search/all?keywords=school+inspection+data+download` |
| BEIS EPC | ✅ Works | `https://www.gov.uk/guidance/energy-performance-of-buildings-data` |
| DEFRA Air Quality | ✅ Works | `https://uk-air.defra.gov.uk/data/` (API key needed) |
| CQC Care Quality | ✅ Works | `https://www.cqc.org.uk/about-us/transparency/using-cqc-data` |
| Land Registry | ✅ Works | `https://www.gov.uk/guidance/land-registry-data` |
| DfT Road Safety | ✅ Works | `https://www.data.gov.uk/dataset/cb7ae6f0-4be6-4935-9277-47e5ce24a11f/road-accidents-safety-data` |

**Notes:**
### UK-Wide Deprivation (beyond English IMD)

| Source | URL | Status | Coverage | Notes |
|--------|-----|--------|----------|-------|
| **Scottish IMD** | https://simd.scot/ | ✅ Works | Scotland | Latest is 2020v2, needs 2024 refresh |
| **Welsh IMD 2025** | https://www.gov.wales/welsh-index-multiple-deprivation-2025-series | ✅ Works | Wales | 2025 series available |
| **Northern Ireland IMD** | https://www.nisra.gov.uk/statistics/people-and-communities/deprivation-and-poverty | ✅ Works | N. Ireland | Via NISRA |

### MySociety

| Source | URL | Status | Data | Notes |
|--------|-----|--------|------|-------|
| **MapIt** | https://mapit.mysociety.org/ | ✅ Works | Postcode lookup | Returns GSS codes, LSOA/MSOA |
| **TheyWorkForYou** | https://www.theyworkforyou.com/api/ | ⚠️ Key needed | Parliamentary | Free API key available |

### Poverty & Deprivation (beyond IMD)

| Source | URL | Status | Data | Notes |
|--------|-----|--------|------|-------|
| **ONS Income by area** | https://www.ons.gov.uk/search?q=household+income+by+area | ✅ Works | Income data | Need specific dataset URL |
| **ONS Disability by area** | https://www.ons.gov.uk/search?q=disability+by+area | ✅ Works | Disability data | Need specific dataset |
| **ONS Fuel Poverty** | https://www.ons.gov.uk/search?q=fuel+poverty | ✅ Works | Fuel poverty | Need specific dataset |
| **DWP Child Poverty** | https://www.gov.uk/search/all?keywords=child+poverty+local+authority | ✅ Works | Child poverty | Need specific URL |

**Sources with URL issues (need more search):**
- ONS Small Area Income data - URLs keep changing
- DWP Child Poverty - datasets moved around
- Welsh IMD 2025 - ODS URLs returning 404, DataMapWales needs alternative access

## Implementation Notes

### EPC Data (Energy Performance Certificates)
- **URL:** Verified working - https://assets.publishing.service.gov.uk/media/.../D1-_Domestic_Properties.ods
- **Format:** ODS (OpenDocument Spreadsheet)
- **Requires:** `odfpy` library for parsing
- **Data:** Energy efficiency ratings by local authority (A-G ratings)
- **Indicators:** housing.epc.average_rating, housing.epc.a_rating_pct, etc.

### Welsh IMD 2025
- **URL:** https://www.gov.wales/welsh-index-multiple-deprivation-2025
- **Issue:** Direct ODS download links returning 404
- **Alternative:** DataMapWales (https://datamap.gov.wales/maps/welsh-index-of-multiple-deprivation-wimd-2025/) - requires WFS API
- **Recommendation:** Postpone until stable download URL available

### MapIt API
- **URL:** Verified working - https://mapit.mysociety.org/postcode/{postcode}
- **Use case:** Geocoding enhancement (beyond postcodes.io)
- **Not a data source:** This is a geocoding service, not indicator data

## Priority Recommendations

| Priority | Source | Effort | Dependencies | Status |
|----------|--------|--------|---------------|--------|
| 1 | EPC Data | Medium | odfpy library | Download verified, parsing needed |
| 2 | Ofcom Connected Nations | Medium | CSV/Excel download | Need URL search |
| 3 | Ofsted | Medium | CSV/Excel download | Need URL search |
| 4 | Welsh IMD | High | WFS API | Postponed - unstable URLs |

## Objective

Expand Soundings beyond current 8 domains (population, deprivation, economy, health, education, housing, crime, civil society) with high-value neighbourhood data that communities, local authorities, and researchers find actionable.

## Recommended Priority Data Sources

### Priority 1: High Impact, Clear APIs

| # | Source | Domain | Indicators | Data Format | API Availability |
|---|--------|--------|-------------|-------------|------------------|
| 1 | Ofcom Connected Nations | Digital | Broadband speeds (download/upload), mobile coverage (4G/5G), full-fibre availability | CSV + JSON | API docs published annually |
| 2 | Ofsted | Education | School overall rating, inspection date, pupil outcomes | CSV bulk download | Monthly XML/CSV |
| 3 | BEIS Energy Performance | Housing | EPC ratings (A-G), median rating, property types | CSV bulk download | Updated quarterly |
| 4 | DEFRA Air Quality | Environment | NO2, PM2.5, ozone levels, station data | JSON API | Real-time + historical |
| 5 | CQC Care Quality | Health | Care home ratings, service types, capacities | CSV/API | Monthly updates |
| 6 | Land Registry | Housing | House price paid, property type, new/old build | CSV bulk | Monthly |
| 7 | DfT Road Safety | Safety | Accident severity, vehicle types, casualties by location | CSV | Annual |

### Priority 2: Medium Impact

| # | Source | Domain | Indicators |
|---|--------|--------|------------|
| 8 | NHS Digital | Health | GP access, dental availability, hospital waiting times |
| 9 | Valuation Office | Housing | Council tax bands, rateable values |
| 10 | Companies House | Economy | Active companies per area, new incorporations |
| 11 | ONS Business Register | Economy | Business count by sector, turnover |

### Priority 3: Nice to Have

| # | Source | Domain | Indicators |
|---|--------|--------|------------|
| 12 | Flood Risk (EA) | Environment | Flood warnings, risk categories |
| 13 | OS OpenData | Environment | Greenspace, rights of way |
| 14 | Bus Open Data | Transport | Timetables, stop accessibility |

---

## Integration Approach

### Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Soundings v1                      │
├─────────────────────────────────────────────────────┤
│  Existing Sources (13)                               │
│  • ONS, DfE, OHID, MHCLG, Police, Charity Commission │
├─────────────────────────────────────────────────────┤
│  New Loader Adapters (Phase 6)                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │ ofcom   │ │ ofsted   │ │ beis_epc │  → loader   │
│  │ loader  │ │ loader   │ │ loader   │    mode     │
│  └──────────┘ └──────────┘ └──────────┘             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │ defra   │ │   cqc    │ │  land    │             │
│  │ loader  │ │ loader   │ │ registry │             │
│  └──────────┘ └──────────┘ └──────────┘             │
├─────────────────────────────────────────────────────┤
│  New Indicator Catalogue (50+ new metrics)          │
└─────────────────────────────────────────────────────┘
```

### Implementation Pattern

1. **Add source to `catalogue/sources.yaml`**
   ```yaml
   - id: ofcom.connected_nations
     label: Ofcom Connected Nations
     publisher: Ofcom
     publisher_url: https://www.ofcom.org.uk/
     licence: OGL-UK-3.0
     mode: loader
     refresh_cadence: "0 2 1 4 *"  # Annual, April
   ```

2. **Create loader adapter** (if bulk download) or **passthrough** (if API)
   - Loaders: inherit from `BaseLoader`, implement `fetch()` → DB insert
   - Passthrough: implement read-only API proxy

3. **Add indicators to `catalogue/indicators.yaml`**
   ```yaml
   - key: digital.broadband.avg_download_speed
     label: Average broadband download speed
     unit: Mbps
     higher_is: better
     domains: [digital]
     available_at: [lsoa, msoa, ltla, utla]
   ```

4. **Add normalisation rules** in `catalogue/sanitisation.yaml`
5. **Write tests** following TDD pattern
6. **Deploy to staging**, verify data quality
7. **Production** via cron schedule

---

## Source-by-Source Breakdown

### 1. Ofcom Connected Nations

**What:** Annual report on broadband and mobile coverage by postcode/area
**URL:** https://www.ofcom.org.uk/content/research-statistics-and-data/connectivity/connected-nations (redirects, need to search for data files)
**Backup:** https://www.ofcom.org.uk/research-and-data (main research page)
**Data:**
- Average broadband download/upload speeds
- Superfast broadband availability (30Mbps+)
- Full-fibre availability
- 4G/5G indoor coverage

**Loader implementation:**
- Bulk CSV download (published ~April each year)
- Geographic resolution: postcode sector → can aggregate to LSOA/MSOA
- Estimate ~30k postcode sectors → 6.5k LSOAs via lookup

**Indicator candidates:**
```
digital.broadband.avg_download_speed     (Mbps)
digital.broadband.avg_upload_speed       (Mbps)
digital.broadband.superfast_availability (%)
digital.broadband.full_fibre_availability (%)
digital.mobile.4g_coverage_indoor         (%)
digital.mobile.5g_coverage               (%)
```

---

### 2. Ofsted

**What:** School inspection results and ratings
**URL:** https://www.gov.uk/search/all?keywords=school+inspection+data+download (search results)
**Data portal:** https://www.gov.uk/government/publications/?keyword=ofsted+data
**Data:**
- Overall effectiveness rating (4-tier: Outstanding/Good/Requires Improvement/Inadequate)
- Inspection date
- Pupil attainment scores

**Loader implementation:**
- Monthly CSV/XML export from Ofsted portal
- Join on school URN via DfE data

**Indicator candidates:**
```
education.schools.overall_outstanding_pct
education.schools.overall_good_pct
education.schools.requires_improvement_pct
education.schools.independent_outstanding_pct
```

---

### 3. BEIS Energy Performance (EPC)

**What:** Energy Performance Certificates for domestic properties
**URL:** https://www.gov.uk/guidance/energy-performance-of-buildings-data
**Data:**
- EPC rating (A-G)
- Property type
- Built form
- Floor area

**Loader implementation:**
- Quarterly full export (~4GB, ~25M rows)
- Use latest batch only, no historical
- Aggregate to LSOA level

**Indicator candidates:**
```
housing.epc.median_rating
housing.epc.a_pct
housing.epc.b_pct
housing.epc.c_pct
housing.epc.d_pct
housing.epc.e_pct
housing.epc.f_pct
housing.epc.g_pct
```

---

### 4. DEFRA Air Quality

**What:** UK AIR pollution data from monitoring stations
**URL:** https://uk-air.defra.gov.uk/data/
**API:** https://api.environment.data.gov.uk/air-quality
**Data:**
- NO2, PM2.5, PM10, O3, SO2 concentrations
- Hourly/daily averages

**Passthrough implementation:**
- Direct API proxy to DEFRA endpoints
- No local DB storage needed (real-time)

**Indicator candidates:**
```
environment.air.no2.annual_mean        (μg/m³)
environment.air.pm25.annual_mean       (μg/m³)
environment.air.pm10.annual_mean       (μg/m³)
environment.air.o3.annual_mean         (μg/m³)
environment.air.exceedances_no2_days   (days)
```

---

### 5. CQC Care Quality

**What:** Care home and social care provider ratings
**URL:** https://www.cqc.org.uk/about-us/transparency/using-cqc-data (verified 200)
**Data:**
- Overall rating (Outstanding/Good/Requires Improvement/Inadequate)
- Service type (care home, home care, etc.)
- Capacity, staffing

**Loader implementation:**
- Monthly CSV
- Match to location via postcode

**Indicator candidates:**
```
health.care_homes.outstanding_pct
health.care_homes.good_pct
health.care_homes.inadequate_pct
health.care_homes.beds_total
```

---

### 6. Land Registry Price Paid

**What:** Property transaction prices
**URL:** https://www.gov.uk/guidance/land-registry-data
**Data:**
- Price paid
- Property type (detached, semi, terraced, flat)
- New/old build
- Postcode

**Loader implementation:**
- Monthly CSV (~700k rows/month)
- Aggregate to LSOA by financial year

**Indicator candidates:**
```
housing.prices.median                  (£)
housing.prices.mean                    (£)
housing.prices.detached_median         (£)
housing.prices.semi_median             (£)
housing.prices.terraced_median         (£)
housing.prices.flat_median             (£)
housing.prices.new_build_median        (£)
housing.prices.transaction_count      (count)
```

---

### 7. DfT Road Safety

**What:** Personal injury road accidents
**URL:** https://data.gov.uk/dataset/road-accidents-safety-data
**Data:**
- Accident severity (Fatal/Serious/Slight)
- Number of vehicles, casualties
- Location (grid ref)

**Loader implementation:**
- Annual CSV (~120k accidents/year)
- Join to LSOA via grid reference

**Indicator candidates:**
```
safety.road_accidents.fatal_count
safety.road_accidents.serious_count
safety.road_accidents.slight_count
safety.road_accidents.casualty_count
safety.road_accidents.rate_per_1000  (per 1k pop)
```

---

## New Domains Proposed

Add to indicators.yaml domain structure:

```yaml
domains:
  - id: digital
    label: Digital Connectivity
    description: Broadband speeds, mobile coverage, digital inclusion

  - id: environment
    label: Environment
    description: Air quality, flood risk, greenspace

  - id: housing
    label: Housing (extended)
    description: Prices, energy efficiency, tenure
    # existing

  - id: safety
    label: Safety
    description: Road accidents, crime (expand beyond police.uk)
```

---

## Timeline Estimate

| Month | Sources | Indicators | Notes |
|-------|---------|-------------|-------|
| Month 1 | Ofcom | 6 | Annual data, simple loader |
| Month 2 | Ofsted | 4 | CSV join complexity |
| Month 3 | BEIS EPC | 8 | Large dataset, bulk import |
| Month 4 | DEFRA Air | 6 | API proxy, station mapping |
| Month 5 | CQC | 4 | Care homes |
| Month 6 | Land Registry | 8 | Price data |
| Month 7 | DfT Road | 5 | Accident data |
| Month 8+ | Buffer | — | NHS, VOA, Companies House |

**Total new indicators:** ~50+
**Effort per source:** 2-5 days average (loader mode)
**Effort per API passthrough:** 1-2 days

---

## Technical Considerations

### Large Data Loads

- **EPC:** 25M rows, 4GB — consider PostgreSQL COPY, batch processing
- **Land Registry:** 700k/month — incremental loads, deduplicate by transaction_id
- **EPC + Land Registry:** May need dedicated tables, not in main indicator_value

### Geographic Resolution

- Most data is postcode-level → requires ONS lookup to LSOA/MSOA
- Use existing `geography.postcode` table for mapping
- Budget for ~5% unmatched postcodes

### Rate Limits

- DEFRA API: 5 requests/second (documented)
- Ofcom: Bulk download only
- CQC: Monthly CSV via portal

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Source URL changes | Medium | High | Pin to specific CSV versions in catalog |
| Geographic mapping gaps | Medium | Medium | Log unmapped postcodes, improve geocoding |
| API changes | Low | Medium | Version pinning, fallback to cached data |
| Large import time | High | Low | Background cron, progressive UI loading |

---

## Next Steps

1. **Validate sources** — Check each URL is still active, API keys not required
2. **Source POC loaders** — Build skeleton loader for top 2 sources
3. **Indicator spec** — Define precise indicator keys and units
4. **Staging deployment** — Test with subset of data
5. **Full implementation** — Following TDD

---

## Questions for Review

- [ ] Which source should we tackle first?
- [ ] Any sources we should skip or deprioritise?
- [ ] Should we combine any sources into a single loader PR?
- [ ] Are there API keys required for any of these? (DEFRA does, needs registration)

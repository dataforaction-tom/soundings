# Phase 6 Data Sources Plan

**Date:** 2026-05-24 (updated 2026-06-29)
**Status:** Revised — NDL exploration complete, new sources added
**Parent:** PLAN.md — Phase 6

## National Data Library (data.gov.uk)

The site has been rebranded as the **National Data Library** and restructured into 6 curated collections with ~60+ sub-topics. Each sub-topic has verified data links, chart data downloads, and direct API/bulk-download access.

### NDL Collections (browsed 2026-06-29)

| Collection | Sub-topics | Phase 6 relevance |
|---|---|---|
| **Environment** | Weather, Air quality, Water quality, Long term flood risk, Flood alerts, Storm overflows, Main rivers, Coastal erosion, Climate projections, Environmental public registers, LIDAR mapping, Aerial photography, Landfill sites, Road noise, Rail noise, Forest and woodlands, Non-woodland trees, SSSI | Air quality, Flood risk, Noise pollution, Greenspace |
| **Land and property** | UK house prices, Property price paid, Land ownership, Planning data, Addresses, Dwelling stock (incl. vacancies), Rents/lettings/tenancies, English Housing Survey, Housing supply, Energy performance of buildings, Fire statistics | EPC, Land Registry, Housing supply, Rents, Vacancies |
| **People** | Births, Deaths, Public health dashboard, Population estimates, Immigration, Social mobility, Deprivation, Homelessness, Police recorded crime, Courts management, Early years inspections, State-funded schools inspections, Pupil attendance, Compare school performance, Vocational qualifications, Museum/gallery visits, Family food statistics | Ofsted, Deprivation, Homelessness, Health, Education, Crime |
| **Business and economy** | UK trade, Inflation, Interest rates, Get company information, Get charity information, Food hygiene ratings, Fuel/oil prices, Energy prices, Electricity, Agricultural commodity prices | Companies House, Charity Commission |
| **Transport** | Road traffic, Road safety, Road conditions, Real-time train info, Bus statistics, MOT test results, Driving tests, Fishing vessels, National Travel Survey, Transport connectivity, Maritime/shipping | Road safety, Bus, Traffic, Connectivity |
| **Government** | (not fully browsed — session dropped) | TBD |

## Validation Status

### Phase 6 Original Sources — NDL Mapping

| Source | NDL Collection | NDL Sub-topic | NDL Status | Verified URL |
|--------|----------------|---------------|------------|--------------|
| DEFRA Air Quality | Environment | Air quality | ✅ Listed | `https://get-air-pollution-data.service.gov.uk/` (AURN, CSV downloads, data since 2018) |
| BEIS EPC | Land & property | Energy performance of buildings | ✅ Listed | `https://www.gov.uk/guidance/energy-performance-of-buildings-data` |
| Land Registry (HPI) | Land & property | UK house prices | ✅ Listed | `https://landregistry.data.gov.uk/app/ukhpi/` + downloads at `https://www.gov.uk/government/statistical-data-sets/uk-house-price-index-data-downloads-december-2025` |
| Land Registry (transactions) | Land & property | Property price paid | ✅ Listed | Separate sub-topic from HPI |
| Ofsted (schools) | People | State-funded schools inspections and outcomes | ✅ Listed | Via NDL → Ofsted data portal |
| Ofsted (early years) | People | Early years and childcare inspections and outcomes | ✅ Listed | Separate sub-topic |
| DfT Road Safety | Transport | Road safety | ✅ Listed | Via NDL → DfT |
| Companies House | Business & economy | Get company information | ✅ Listed | |
| Charity Commission | Business & economy | Get charity information | ✅ Listed | |
| Flood Risk (EA) | Environment | Long term flood risk + Flood alerts | ✅ Listed | Two sub-topics |
| Bus Open Data | Transport | Bus statistics | ✅ Listed | |
| CQC Care Quality | (not in NDL collections) | — | ⚠️ Still direct | `https://www.cqc.org.uk/about-us/transparency/using-cqc-data` |
| Ofcom Connected Nations | (not in NDL collections) | — | ⚠️ Still direct | `https://www.ofcom.org.uk/research-and-data` |

### UK-Wide Deprivation (beyond English IMD)

| Source | URL | Status | Coverage | Notes |
|--------|-----|--------|----------|-------|
| **Scottish IMD** | https://simd.scot/ | ✅ Works | Scotland | Latest is 2020v2, needs 2024 refresh |
| **Welsh IMD 2025** | https://www.gov.wales/welsh-index-multiple-deprivation-2025-series | ✅ Works | Wales | 2025 series available |
| **Northern Ireland IMD** | https://www.nisra.gov.uk/statistics/people-and-communities/deprivation-and-poverty | ✅ Works | N. Ireland | Via NISRA |
| **NDL Deprivation** | `https://www.data.gov.uk/collections/people/deprivation` | ✅ Listed | UK-wide? | New NDL sub-topic — needs investigation |

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

## Priority Recommendations (Revised)

| Priority | Source | Effort | Dependencies | NDL Listed? | Status |
|----------|--------|--------|---------------|-------------|--------|
| 1 | EPC Data | Medium | odfpy library | ✅ Land & property | Download verified, parsing needed |
| 2 | DEFRA Air Quality | Medium | AURN CSV API | ✅ Environment | New URL: `get-air-pollution-data.service.gov.uk` |
| 3 | Land Registry (HPI + transactions) | Medium | CSV bulk download | ✅ Land & property (2 sub-topics) | URLs verified via NDL |
| 4 | Ofsted (schools + early years) | Medium | CSV/Excel download | ✅ People (2 sub-topics) | Access via NDL |
| 5 | DfT Road Safety | Medium | CSV bulk | ✅ Transport | Access via NDL |
| 6 | Ofcom Connected Nations | Medium | CSV/Excel download | ❌ Not in NDL | Need direct URL search |
| 7 | CQC Care Quality | Medium | CSV monthly | ❌ Not in NDL | Direct from CQC |
| 8 | Homelessness | Low-Medium | ONS/direct | ✅ People | NEW — not in original plan |
| 9 | Dwelling stock & vacancies | Low-Medium | DLUHC | ✅ Land & property | NEW — not in original plan |
| 10 | Rents & lettings | Medium | ONS | ✅ Land & property | NEW — not in original plan |
| 11 | Flood Risk (EA) | High | API | ✅ Environment (2 sub-topics) | Access via NDL |
| 12 | Welsh IMD | High | WFS API | ❌ Not in NDL | Postponed — unstable URLs |

## Objective

Expand Soundings beyond current 8 domains (population, deprivation, economy, health, education, housing, crime, civil society) with high-value neighbourhood data that communities, local authorities, and researchers find actionable.

**Revised scope (2026-06-29):** NDL exploration revealed additional high-value sources not in original plan — homelessness, dwelling stock/vacancies, rents, transport connectivity, noise pollution, greenspace. Total new indicators now estimated at **65-80+** across **5-6 new domains**.

## Recommended Priority Data Sources

### Priority 1: High Impact, Clear APIs

| # | Source | Domain | Indicators | Data Format | API Availability | NDL Listed? |
|---|--------|--------|-------------|-------------|------------------|-------------|
| 1 | Ofcom Connected Nations | Digital | Broadband speeds (download/upload), mobile coverage (4G/5G), full-fibre availability | CSV + JSON | API docs published annually | ❌ Not in NDL |
| 2 | Ofsted (schools) | Education | School overall rating, inspection date, pupil outcomes | CSV bulk download | Monthly XML/CSV | ✅ People |
| 2b | Ofsted (early years) | Education | Nursery/childcare inspection ratings | CSV bulk download | Monthly | ✅ People (separate sub-topic) |
| 3 | BEIS Energy Performance | Housing | EPC ratings (A-G), median rating, property types | CSV bulk download | Updated quarterly | ✅ Land & property |
| 4 | DEFRA Air Quality | Environment | NO2, PM2.5, ozone levels, station data | CSV via AURN service | Real-time + historical, `get-air-pollution-data.service.gov.uk` | ✅ Environment |
| 5 | CQC Care Quality | Health | Care home ratings, service types, capacities | CSV/API | Monthly updates | ❌ Not in NDL |
| 6 | Land Registry (HPI) | Housing | House price index, average prices by type/area | CSV bulk | Monthly | ✅ Land & property |
| 6b | Land Registry (Price Paid) | Housing | Transaction prices, property type, new/old build | CSV bulk | Monthly | ✅ Land & property (separate sub-topic) |
| 7 | DfT Road Safety | Safety | Accident severity, vehicle types, casualties by location | CSV | Annual | ✅ Transport |

### Priority 2: Medium Impact

| # | Source | Domain | Indicators | NDL Listed? |
|---|--------|--------|------------|-------------|
| 8 | NHS Digital | Health | GP access, dental availability, hospital waiting times | ❌ |
| 9 | Valuation Office | Housing | Council tax bands, rateable values | ❌ |
| 10 | Companies House | Economy | Active companies per area, new incorporations | ✅ Business & economy |
| 11 | ONS Business Register | Economy | Business count by sector, turnover | ❌ |
| 12 | **Homelessness** (NEW) | Housing/Social | Rough sleeping count, temporary accommodation | ✅ People |
| 13 | **Dwelling stock & vacancies** (NEW) | Housing | Vacancy rates, dwelling count by type | ✅ Land & property |
| 14 | **Rents & lettings** (NEW) | Housing | Private/social rent levels, new lettings | ✅ Land & property |
| 15 | **Transport connectivity** (NEW) | Transport | Journey times, accessibility indices | ✅ Transport |

### Priority 3: Nice to Have

| # | Source | Domain | Indicators | NDL Listed? |
|---|--------|--------|------------|-------------|
| 16 | Flood Risk (EA) | Environment | Flood warnings, risk categories | ✅ Environment (2 sub-topics) |
| 17 | OS OpenData | Environment | Greenspace, rights of way | ❌ |
| 18 | Bus Open Data | Transport | Timetables, stop accessibility | ✅ Transport |
| 19 | **Road/Rail noise** (NEW) | Environment | Noise pollution levels by area | ✅ Environment (2 sub-topics) |
| 20 | **Forest & woodlands** (NEW) | Environment | Tree canopy, greenspace coverage | ✅ Environment |
| 21 | **Food hygiene ratings** (NEW) | Health/Safety | Restaurant/shop hygiene by area | ✅ Business & economy |
| 22 | **Pupil attendance** (NEW) | Education | School absence rates | ✅ People |
| 23 | **Social mobility** (NEW) | Education/Economy | Social mobility index by area | ✅ People |
| 24 | **Water quality** (NEW) | Environment | River/coastal quality | ✅ Environment |

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
**URL:** https://get-air-pollution-data.service.gov.uk/ (NDL-verified, AURN service)
**Legacy URL:** https://uk-air.defra.gov.uk/data/ (still works)
**API:** https://api.environment.data.gov.uk/air-quality
**Data:**
- NO2, PM2.5, PM10, O3, SO2 concentrations
- Hourly/daily/annual averages
- Data available since 2018 per station
- Custom dataset builder: select pollutants, date range, area
- Download as CSV

**Passthrough implementation:**
- Direct API proxy to DEFRA endpoints
- No local DB storage needed (real-time)
- Alternative: bulk CSV download from AURN service for annual averages

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

### 8. Homelessness (NEW — from NDL People)

**What:** Rough sleeping counts and temporary accommodation data
**URL:** https://www.data.gov.uk/collections/people/homelessness
**Data:**
- Rough sleeping count (annual snapshot + monthly estimates)
- Temporary accommodation placements
- Homelessness acceptances and decisions
- Prevention and relief duties

**Loader implementation:**
- ONS/MHCLG published data
- Available at LTLA level (some at LSOA)
- Annual + quarterly updates

**Indicator candidates:**
```
housing.homelessness.rough_sleeping_count
housing.homelessness.temp_accommodation_count
housing.homelessness.acceptances_per_1000
housing.homelessness.prevention_count
```

---

### 9. Dwelling Stock & Vacancies (NEW — from NDL Land & property)

**What:** Housing stock, vacant dwellings, dwelling types
**URL:** https://www.data.gov.uk/collections/land-and-property/dwelling-stock-including-vacancies
**Data:**
- Total dwelling stock by type (house, flat, bungalow)
- Vacancy rates (long-term vacant)
- Second homes
- Local authority level

**Loader implementation:**
- DLUHC published data
- CSV/Excel annual
- Available at LTLA level

**Indicator candidates:**
```
housing.stock.total_dwellings
housing.stock.vacant_pct
housing.stock.second_homes_count
housing.stock.flats_pct
```

---

### 10. Rents & Lettings (NEW — from NDL Land & property)

**What:** Private and social rent levels, new lettings
**URL:** https://www.data.gov.uk/collections/land-and-property/rents-lettings-and-tenancies
**Data:**
- Median monthly rent by property type
- Social rent levels
- Private rented sector size
- New lettings per quarter

**Loader implementation:**
- ONS Private Rental Market statistics
- CSV quarterly
- Available at LTLA/region level

**Indicator candidates:**
```
housing.rents.median_monthly
housing.rents.median_monthly_2br
housing.rents.social_avg
housing.rents.new_lettings_count
```

---

### 11. Transport Connectivity (NEW — from NDL Transport)

**What:** Journey time accessibility, transport connectivity indices
**URL:** https://www.data.gov.uk/collections/transport/transport-connectivity
**Data:**
- Journey times to key services (employment, healthcare, education)
- Public transport accessibility scores
- Rural/urban connectivity gap

**Loader implementation:**
- DfT Transport Connectivity statistics
- CSV annual
- Available at LTLA level

**Indicator candidates:**
```
transport.connectivity.journey_time_employment
transport.connectivity.journey_time_gpprimary
transport.connectivity.journey_time_hospital
transport.connectivity.public_transport_score
```

---

### 12. Road/Rail Noise (NEW — from NDL Environment)

**What:** Noise mapping data for roads and railways
**URL:** https://www.data.gov.uk/collections/environment/road-noise + rail-noise
**Data:**
- Noise exposure levels (Lden, Lnight) by area
- Population exposed to high noise levels
- Source: DEFRA noise mapping (5-year cycle)

**Loader implementation:**
- DEFRA noise mapping outputs
- Shapefile/CSV
- Available at LSOA level via grid reference

**Indicator candidates:**
```
environment.noise.road_laeq
environment.noise.rail_laeq
environment.noise.population_exposed_high_pct
```

---

### 13. Forest & Woodlands (NEW — from NDL Environment)

**What:** Tree canopy and woodland coverage
**URL:** https://www.data.gov.uk/collections/environment/forest-and-woodlands
**Data:**
- Woodland area by type (broadleaf, conifer, mixed)
- Tree canopy coverage
- Ancient woodland inventory

**Loader implementation:**
- Forestry Commission / Natural England
- Shapefile → aggregate to LSOA/LTLA
- 5-year cycle

**Indicator candidates:**
```
environment.greenspace.woodland_area_pct
environment.greenspace.ancient_woodland_count
environment.greenspace.tree_canopy_pct
```

---

### 14. Pupil Attendance (NEW — from NDL People)

**What:** School absence and attendance rates
**URL:** https://www.data.gov.uk/collections/people/pupil-attendance
**Data:**
- Overall absence rate
- Persistent absence rate (>10% sessions missed)
- Authorised vs unauthorised absences
- By school type and pupil characteristics

**Loader implementation:**
- DfE published data
- CSV termly
- Available at school/LSOA level

**Indicator candidates:**
```
education.attendance.overall_absence_rate
education.attendance.persistent_absence_rate
education.attendance.unauthorised_absence_rate
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
    description: Air quality, flood risk, noise pollution, greenspace, water quality

  - id: housing
    label: Housing (extended)
    description: Prices, energy efficiency, tenure, rents, vacancies, homelessness
    # existing

  - id: safety
    label: Safety
    description: Road accidents, crime (expand beyond police.uk)

  - id: transport
    label: Transport
    description: Connectivity, bus, traffic volumes, journey times
```

---

## Timeline Estimate (Revised)

| Month | Sources | Indicators | Notes |
|-------|---------|-------------|-------|
| Month 1 | EPC + DEFRA Air | 14 | Both NDL-verified, bulk CSV |
| Month 2 | Land Registry (HPI + Price Paid) | 16 | Two NDL sub-topics, bulk CSV |
| Month 3 | Ofsted (schools + early years) | 8 | Two NDL sub-topics, CSV join |
| Month 4 | DfT Road Safety + Homelessness | 9 | NDL Transport + People |
| Month 5 | Dwelling stock + Rents | 12 | NDL Land & property, CSV |
| Month 6 | Ofcom + CQC | 10 | Direct (not in NDL), CSV/API |
| Month 7 | Pupil attendance + Transport connectivity | 7 | NDL People + Transport |
| Month 8+ | Buffer | — | Noise, Greenspace, Food hygiene, Water quality, Social mobility, Flood risk, Welsh IMD |

**Total new indicators:** ~75-85+
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

- [ ] Which source should we tackle first? (Recommendation: EPC + DEFRA Air — both NDL-verified, bulk CSV, no API keys)
- [ ] Should we bundle NDL-discovered sources (homelessness, dwelling stock, rents) into a single "housing extended" PR?
- [ ] Any sources we should skip or deprioritise?
- [ ] Are there API keys required for any of these? (DEFRA API does, needs registration; AURN CSV downloads are free)
- [ ] Should we investigate the NDL Deprivation sub-topic for UK-wide IMD coverage?
- [ ] Should the Government collection be browsed for additional sources? (session dropped during exploration)
- [x] ~~Which source should we tackle first?~~ — Revised: start with EPC + DEFRA Air (NDL-verified)
- [x] ~~Should we combine any sources into a single loader PR?~~ — Yes: bundle housing-related sources
- [x] ~~Are there API keys required?~~ — DEFRA API yes, AURN CSV no. Others TBD per source.

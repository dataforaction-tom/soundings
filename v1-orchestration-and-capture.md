# Soundings v1 — Orchestration & Capture

**Status:** Draft 0.2
**Scope:** The MCP server, the indicator catalogue, the geography spine, and the questions corpus capture layer. Designed to run on a single machine.
**Related:** [README](./README.md) · [v1.5](./v1.5-just-in-time-interfaces.md) · [v2](./v2-context-layer.md) · [v3](./v3-contribution-layer.md)

---

## 1. Purpose

v1 delivers two things, both useful on day one without any external participation:

1. **Orchestration.** A single MCP server wraps a curated set of UK open data sources behind a small, stable, question-shaped tool surface. LLMs and humans can ask coherent questions about needs in a place without having to know which government department holds which dataset.
2. **Capture.** Every interaction with the orchestration layer is logged as a structured record, with consent. The resulting corpus becomes a public artefact in its own right.

v1.5 adds richer interfaces over the same capture and orchestration layers. v2 and v3 add context and contribution from organisations. The v1 contracts established here do not change in later versions; they only get more sources behind them.

---

## 2. Deployment model

Designed to run as a single Docker Compose stack on one machine.

```
┌──────────────────────────────────────────────────────────┐
│  Mac mini / single-host deployment                        │
│                                                            │
│  ┌──────────────────┐    ┌──────────────────────────┐    │
│  │  soundings-mcp   │    │  soundings-ui            │    │
│  │  (Python/FastAPI │    │  (Astro static + minimal │    │
│  │   + MCP)         │◄───┤   server-rendered pages) │    │
│  └────────┬─────────┘    └──────────────────────────┘    │
│           │                                                │
│  ┌────────▼──────────────────────────────────────────┐   │
│  │  Postgres (geography spine, cache, corpus store)   │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │  Caddy / reverse proxy + Cloudflare Tunnel        │   │
│  └────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
                              │
                              ▼
                  Public origin via Cloudflare
```

**Component choices justified:**

- **Python/FastAPI** for the server. Mature ecosystem for MCP, easy adapter authoring, comfortable for the client work this comes out of. Async-native for concurrent upstream calls.
- **Postgres** for everything stateful. Geography spine, source caches, questions corpus, all in one database. JSONB for flexible schema, full-text search built in, easy to back up. No separate vector store in v1 — added in v1.5 if needed.
- **Astro for the UI.** Server-rendered, minimal JavaScript, easy to host. The UI is intentionally thin in v1.
- **Cloudflare Tunnel** for public exposure without opening ports. Matches existing Good Ship infrastructure. Means the Mac mini can host without static IP or port forwarding.

**Resource envelope on a Mac mini:** comfortably fits in 16GB RAM, ~50GB disk for data and caches. Geography spine is the largest single data load (~3GB including boundaries). All upstream calls are cached aggressively.

---

## 3. The geography spine

Every spatial reference in the system normalises to one of:

- `postcode` (used as input, never stored as the canonical reference)
- `lsoa21` (Lower Super Output Area, 2021 boundaries)
- `msoa21`
- `ltla24` (Lower Tier Local Authority, current boundaries)
- `utla24` (Upper Tier Local Authority)
- `region`
- `country` (within UK)
- `westminster_constituency_24`
- `ward24` (electoral ward, current boundaries)

Internal canonical geography ID format: `{type}:{code}` — e.g. `lsoa21:E01001234`, `ltla24:E07000223`.

The geography service handles:

- Postcode → all containing geographies (via postcodes.io, with local cache)
- Lookups between geography levels (via ONS Open Geography Portal, loaded once at deploy time)
- Boundary change history (via ONS Code History Database)
- Best-effort fallback when an upstream source still uses older codes
- Boundary geometries for display (simplified for web use)

This service is internal and not exposed as a tool directly; it underlies every spatial query. A failure in the geography spine fails the request — Soundings will not silently approximate.

---

## 4. Tool surface

Six tools. Each is question-shaped. Behind each, the server may call multiple sources. The contract for each is stable across all future versions.

### 4.1 `find_place`

Resolve a natural-language place reference to a canonical geography.

```yaml
input:
  query: string  # "Stockton-on-Tees", "TS18 1AB", "north Tyneside"
  geography_types: [string] | optional  # filter to specific levels
output:
  matches:
    - id: string         # canonical geography ID
      name: string
      type: string
      parent_ids: [string]  # containing geographies
      confidence: float
```

### 4.2 `get_place_profile`

A baseline summary of a place. Used to ground further questions.

```yaml
input:
  place_id: string  # canonical geography ID
  include: [string] | optional  # ["population", "deprivation", "economy", ...]
output:
  place:
    id: string
    name: string
    type: string
  indicators:
    - key: string              # e.g. "population.total"
      value: number | string
      unit: string
      period: string           # e.g. "2021", "2024-Q2"
      source: SourceRef
      confidence: string       # "official", "modelled", "experimental", "experiential"
```

The `confidence: "experiential"` value is reserved for v3 — observations contributed by organisations. v1 only ever returns `"official"`, `"modelled"`, or `"experimental"`.

### 4.3 `get_indicators`

Targeted indicator lookup. The most-used tool.

```yaml
input:
  place_id: string
  indicators: [string]   # canonical indicator keys (see §5)
  period: string | optional   # default: latest available
  format: "wide" | "tall" | optional
output:
  results:
    - place_id: string
      indicator: string
      value: number | null
      unit: string
      period: string
      source: SourceRef
      methodology_note: string | optional
      caveats: [string]
```

### 4.4 `compare_places`

Comparison across multiple places on shared indicators. Includes percentile context where available.

```yaml
input:
  place_ids: [string]
  indicators: [string]
  comparison_basis: "absolute" | "rate" | "percentile" | optional
output:
  comparisons:
    - indicator: string
      unit: string
      period: string
      values:
        - place_id: string
          value: number
          rank: integer | optional
          percentile: number | optional
      source: SourceRef
```

### 4.5 `get_trend`

Time series for a single indicator at a single place.

```yaml
input:
  place_id: string
  indicator: string
  period_from: string | optional
  period_to: string | optional
output:
  trend:
    place_id: string
    indicator: string
    unit: string
    points:
      - period: string
        value: number
        revised: boolean
    source: SourceRef
    breaks_in_series: [string]   # methodology change notes
```

### 4.6 `find_organisations_in_place`

Civil society context. What organisations are working in this place, what they're funded for.

```yaml
input:
  place_id: string
  activity_filter: [string] | optional   # broad themes
  funded_only: boolean | optional
output:
  organisations:
    - id: string                # Charity Commission number, Companies House number
      name: string
      classification: [string]  # ICNPO or similar
      registered_address_place_id: string | optional
      operates_in_place_ids: [string]
      recent_grants:            # if funded_only or as default summary
        - funder: string
          amount: number
          date: string
          purpose: string
          source: SourceRef
```

---

## 5. Indicator catalogue

Indicators live in a versioned, machine-readable catalogue at `/catalogue/indicators.yaml` in the repo. Each entry:

```yaml
- key: deprivation.imd_score
  label: "Index of Multiple Deprivation score"
  description: "Combined IMD score (England, 2019)."
  unit: "score"
  higher_is: "worse"
  source_id: "mhclg.imd2019"
  available_at: ["lsoa21", "ltla24"]
  refresh_cadence: "every 4-5 years"
  caveats:
    - "Not directly comparable across UK nations."
  related_keys:
    - "deprivation.income"
    - "deprivation.health"
```

The catalogue is the contract between the server and consumers. New indicators are additive; deprecations follow a documented lifecycle.

**v1 priority indicators (target ~50, not exhaustive):**

| Domain | Examples |
|---|---|
| Population | Total, age structure, ethnicity, household composition |
| Deprivation | IMD overall + domains, child poverty AHC |
| Economy | Employment rate, claimant count, median pay |
| Health | Life expectancy, healthy life expectancy, key Fingertips indicators |
| Education | FSM eligibility, KS4 attainment, attendance |
| Housing | Affordability ratio, statutory homelessness, social stock |
| Crime | Recorded crime rate, ASB rate |
| Civil society | Active charities count, total grants in (last 12m) |

Each indicator entry includes the lowest geography it's available at. The server will refuse rather than silently approximate.

---

## 6. Source adapters

Each upstream source is a separate adapter implementing a small interface:

```python
class SourceAdapter:
    source_id: str
    licence: str
    rate_limit: RateLimitPolicy

    async def fetch_indicator(
        self, indicator_key: str, place_id: str, period: str | None
    ) -> IndicatorValue | None: ...

    async def list_available_indicators(self) -> list[str]: ...

    def get_source_ref(self) -> SourceRef: ...
```

**v1 adapters:**

| Source ID | Upstream | Notes |
|---|---|---|
| `ons.census2021` | Nomis API | Population, ethnicity, household composition |
| `ons.aps` | Nomis API | Annual Population Survey, employment |
| `mhclg.imd2019` | MHCLG bulk download | Cached locally, refreshed on each MHCLG release |
| `dwp.statxplore` | Stat-Xplore API | Benefit caseloads, child poverty AHC |
| `ohid.fingertips` | Fingertips API | Health and wellbeing indicators |
| `dfe.explore` | DfE Explore Education Statistics API | Attainment, FSM, attendance |
| `mhclg.live_tables` | MHCLG bulk download | Housing affordability, homelessness |
| `police_uk` | data.police.uk API | Recorded crime, ASB |
| `charity_commission` | CC Register API | Active charities, classifications |
| `360giving` | 360Giving Datastore | Grants flowing into a place |
| `find_that_charity` | FTC API | Organisation lookup, classification |
| `postcodes.io` | postcodes.io | Geography resolution (also internal) |
| `ons.geography` | ONS Open Geography Portal | Boundaries and lookups (also internal) |

Adapters are loaded by configuration. Adding a new one is additive — no changes to the tool surface.

---

## 7. Source references

Every value returned carries a `SourceRef`:

```yaml
SourceRef:
  source_id: string          # e.g. "ons.census2021"
  source_label: string       # human-readable
  publisher: string
  publisher_url: string
  dataset_url: string
  retrieved_at: ISO8601 datetime
  cache_status: "live" | "cached" | "stale"
  licence: string            # SPDX identifier or URL
```

This is the bit that makes downstream LLM responses honest. A narrative brief generated by a consuming LLM can cite back to source. In v2, organisational profiles register under their own `source_id` and join the same provenance system. In v3, contributed observations carry their organisation's `source_id` plus a `confidence: "experiential"` flag.

---

## 8. Questions corpus (capture)

Every tool call produces a record. The capture layer runs synchronously but non-blocking — failure to write to the corpus must never break a tool call.

### 8.1 Record shape

```yaml
QuestionRecord:
  id: uuid
  timestamp: ISO8601
  session_id: uuid                 # rotates per session, no persistent user ID
  consent_version: string          # which consent text was shown
  capture_level: "full" | "minimal" | "none"

  # The question
  natural_language_question: string | null   # only if full consent + sanitiser passed
  tool_called: string
  tool_inputs_redacted: object               # sanitised version of the input
  geography_referenced:
    - id: string
      type: string

  # The answer
  indicators_returned: [string]
  sources_used: [string]
  result_status: "ok" | "no_data" | "partial" | "error"
  error_class: string | null

  # Context (self-declared, optional)
  asker_sector: string | null      # "charity" | "funder" | "researcher" |
                                   # "commissioner" | "public" | "other"
  asker_purpose: string | null     # free-text, sanitised, optional

  # Feedback
  marked_useful: boolean | null
```

### 8.2 Consent levels

Three levels, user-selectable:

- **Full** — natural-language question and self-declared context are captured. Becomes part of the published corpus after sanitisation.
- **Minimal** — only the structured fields (tool called, geography, indicators) are captured. Becomes part of the published corpus.
- **None** — nothing is captured. The user can still use the server.

Default is **minimal**, with a clearly-visible toggle to full. The chosen capture level is honoured for every tool call in that session.

### 8.3 Sanitisation pipeline

Before any record enters the publishable store:

1. Strip postcodes at unit level (keep sector or higher).
2. Strip names of organisations under a published size threshold.
3. Strip personal names via a Named Entity Recognition pass.
4. Strip geographic references finer than MSOA in free-text fields.
5. Flag for human review if any sanitisation rule fires more than once on a single record.

A separate **raw store** retains pre-sanitisation records for 30 days for debugging only, on a locked-down system, and is not used for any analytical purpose.

### 8.4 Publication

The published corpus is released:

- As a downloadable dataset (CSV + JSON Lines), refreshed monthly.
- Under CC BY 4.0.
- With a documented schema and sanitisation methodology.

The public **/asks** view that surfaces the corpus visually is part of v1.5, not v1. v1 publishes the raw artefacts only.

---

## 9. Reference UI (v1)

Deliberately minimal. Three pages.

**`/`** — single text box. "What do you want to know about a place?" Below it, a consent banner showing the current capture level and a one-click toggle. Submission produces a structured response with source citations and a "data behind this" expandable panel showing the structured tool calls that built it.

**`/place/{id}`** — auto-generated profile page for any canonical geography. Cards for each indicator domain, source citations, last-updated dates. Bar/line charts only, generated server-side.

**`/about`** — what Soundings is, how capture works, links to the corpus downloads and the spec docs.

The UI talks to the MCP server over HTTP using the same tool surface available to LLM clients. The UI cannot do anything an external client can't.

---

## 10. Local hosting requirements

For the Mac mini (or equivalent) deployment:

- macOS or Linux host, 16GB RAM minimum, 100GB disk
- Docker Desktop or Colima
- Postgres 15+ (containerised)
- Cloudflare Tunnel for public exposure
- A domain (e.g. `soundings.good-ship.co.uk` initially)

A single `docker compose up` should bring up the entire stack. Initial data load (geography spine, indicator catalogue, baseline source caches) is a one-off `make seed` step that runs in roughly an hour.

Backup strategy: nightly Postgres dump to local disk + remote (e.g. Backblaze B2 or rsync to a second machine). Geography spine and source caches are reproducible from upstream so don't strictly need backing up; the questions corpus does.

---

## 11. Out of scope for v1

- Predictive modelling or forecasting.
- Cross-place clustering or "places like mine" recommendations.
- Just-in-time dashboard generation (deferred to [v1.5](./v1.5-just-in-time-interfaces.md)).
- The public `/asks` corpus visualisation (deferred to [v1.5](./v1.5-just-in-time-interfaces.md)).
- Server-side narrative brief generation (deferred to [v1.5](./v1.5-just-in-time-interfaces.md)).
- Authentication beyond capture-level consent. Open access is the default for v1.
- Scotland, Wales, Northern Ireland coverage at full parity with England. Coverage will be uneven in v1; gaps documented in the indicator catalogue.
- Any contribution mechanism for organisations (deferred to [v3](./v3-contribution-layer.md)).
- Organisational context profiles (deferred to [v2](./v2-context-layer.md)).

---

## 12. Open questions

1. **Naming of the indicator namespace.** `population.total` vs `pop.total` vs more verbose. Aim for human-readable; LLMs can handle either.
2. **Default capture level.** Currently proposed as "minimal". Worth user-testing whether "full" should be default with prominent opt-down.
3. **Indicator governance.** Who decides what enters the catalogue and how it's defined? Likely an editorial board model, lightweight, with public RFCs once Soundings has more than one maintainer.

---

## 13. Build sequence (10–12 weeks)

| Phase | Weeks | Deliverable |
|---|---|---|
| 0 | 1 | Repo, CI, Docker Compose scaffolding, Postgres schema, geography spine working end-to-end (postcode → all geographies). |
| 1 | 2–3 | Source adapters for postcodes.io, ONS Census 2021 (Nomis), MHCLG IMD. `find_place`, `get_place_profile`, `get_indicators` shipped against these three. |
| 2 | 2 | Capture layer + sanitisation pipeline. Questions corpus writing for every call. Minimal `/` and `/place/{id}` UI. |
| 3 | 2 | Adapters for Fingertips, DWP Stat-Xplore, DfE, police.uk. `compare_places` and `get_trend` shipped. |
| 4 | 1–2 | Adapters for Charity Commission, 360Giving, Find That Charity. `find_organisations_in_place` shipped. |
| 5 | 1 | First monthly corpus release. Documentation pass. |
| 6 | 1 | Public soft launch on Mac mini. Gather feedback for v1.5. |

Total: roughly 10–12 weeks of focused build.

---

## Appendix A: glossary

- **MCP** — Model Context Protocol. The open standard for connecting LLM clients to external systems.
- **LSOA / MSOA** — Lower / Middle Super Output Area. UK statistical geographies.
- **IMD** — Index of Multiple Deprivation.
- **Sounding** — a single query to the system. Plural: the published corpus.

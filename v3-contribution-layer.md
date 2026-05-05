# Soundings v3 — Contribution layer

**Status:** Draft 0.1
**Scope:** Organisations submit structured observations — claims about local need backed by evidence — that sit alongside official statistics in answers, clearly flagged and provenanced. The translatable observation standard from the original Local Needs Data Bank, evolved.
**Builds on:** [v1](./v1-orchestration-and-capture.md), [v1.5](./v1.5-just-in-time-interfaces.md), [v2](./v2-context-layer.md)
**Related:** [README](./README.md)

---

## 1. Purpose

v1 gave Soundings the ability to answer questions from official data. v1.5 made those answers digestible. v2 let organisations say *who they are and what they see*. v3 lets them say *what they're seeing now*.

A contributed observation is a structured claim, anchored to a place, backed by evidence, attributed to an organisation, and flagged as experiential rather than official. Observations appear in answers alongside ONS data — never silently merged, always clearly labelled.

This is the layer that completes the original vision: not a data bank in the sense of storing numbers, but an insight commons in which the people closest to local need can contribute what they're seeing in a way that's machine-readable, comparable, and trustworthy.

---

## 2. Design intent

The original Local Needs Data Bank's translatable observation standard solved a real problem: organisations had data in many shapes, and the standard let them contribute as long as they could supply *place + numerical value + a translatable wrapper*. v3 extends that pattern in three ways:

1. **Beyond numbers.** An observation can be a number, a rate, a count, a quote, a structured claim, or a qualitative pattern. The schema accommodates all of these without pretending they're equivalent.
2. **Provenance-first.** Every observation is attributable to a v2 context profile. There are no anonymous contributions in v3.
3. **Decoupled from the indicator catalogue.** Official indicators have stable keys defined centrally. Observations can use those keys when they apply, but can also describe their own claim in their own words. The system handles both.

The watchword is **clearly flagged**. Experiential claims should never be passed off as official statistics. The schema, the storage, the tools, and the UI all treat them as a distinct kind of evidence.

---

## 3. The observation

An observation is a claim about a place, made by an organisation, at a moment in time, with evidence attached.

### 3.1 Schema

```yaml
ObservationRecord:
  id: uuid
  context_source_id: string         # the organisation's v2 source_id
  place_ids: [string]               # one or more canonical geography IDs
  period:
    type: "snapshot" | "range" | "ongoing"
    start: ISO8601-date
    end: ISO8601-date | null

  claim:
    statement: string               # short human-readable claim
    indicator_key: string | null    # if it maps to a catalogued indicator
    theme: string                   # required, free-text but normalised
    direction: "increase" | "decrease" | "level" | "presence" | null

  evidence:
    type: "quantitative" | "qualitative" | "mixed"
    quantitative:                   # if applicable
      value: number
      unit: string
      sample_size: integer | null
      methodology_note: string
    qualitative:                    # if applicable
      summary: string
      excerpts: [string] | null     # short anonymised quotes
      methodology_note: string

  confidence:
    self_assessed: "high" | "medium" | "low"
    note: string

  attribution:
    visibility: "public" | "aggregated_only"
    attribute_to: "organisation" | "anonymous_in_aggregate"

  submitted_at: ISO8601
  superseded_by: uuid | null        # for revisions
  withdrawn_at: ISO8601 | null      # for withdrawals
```

### 3.2 What "translatable" means in v3

In the original databank, "translatable" meant: as long as you give place + value, we can wrap your contribution in our standard. In v3 it means something stronger:

- The orchestration layer can **route an observation to a question**. If a user asks "what's housing affordability like in Stockton?" and an organisation has submitted an observation under `housing.affordability` for `ltla24:E06000004`, the brief composer will see it.
- The schema can **carry your evidence shape**. Quantitative observations look like quantitative observations. Qualitative ones look like qualitative ones. Mixed ones look like both.
- The catalogue can **grow from observations**. When many organisations contribute observations under a theme that doesn't yet have a catalogue indicator, that's a signal to the catalogue editorial board.

### 3.3 Lifecycle

Observations are append-only with explicit revision and withdrawal:

- **Submit** a new observation: creates a new record.
- **Supersede** a previous observation: creates a new record with `superseded_by` set on the older one. Both remain visible in the historical corpus.
- **Withdraw** an observation: sets `withdrawn_at`. Hidden from current results. Audit trail preserved.

---

## 4. New tools

### 4.1 `submit_observation`

Authenticated. Available only to organisations with a verified v2 context profile.

```yaml
input:
  observation: ObservationRecord  # without server-generated fields
output:
  observation_id: uuid
  status: "accepted" | "queued_for_review" | "rejected"
  validation_notes: [string]
```

Most submissions are auto-accepted after schema validation and basic checks (the place is in the organisation's declared `geography.primary_places` or a clear extension; the theme is recognised). A small subset go to a queue for editorial review:

- Observations claiming national or supra-regional reach.
- Observations that conflict sharply with recent submissions from other organisations on the same theme and place.
- Observations from newly-indexed profiles (first three submissions auto-reviewed for consistency).

### 4.2 `get_observations`

Read-only. Available to all consumers.

```yaml
input:
  place_id: string | optional
  context_source_id: string | optional
  theme: string | optional
  indicator_key: string | optional
  period_from: ISO8601 | optional
  period_to: ISO8601 | optional
  include_superseded: boolean | optional   # default false
  include_withdrawn: boolean | optional    # default false
output:
  observations: [ObservationRecord]
  total: integer
```

### 4.3 `get_observation_stream`

A summary feed of recent observations across the system. Useful for the public UI and for organisations watching what others in their patch are seeing.

```yaml
input:
  since: ISO8601 | optional
  place_id: string | optional
  themes: [string] | optional
  limit: integer | optional
output:
  stream:
    - observation_id: uuid
      submitted_at: ISO8601
      claim_statement: string
      place_ids: [string]
      theme: string
      organisation_name: string | null   # null if attribution = anonymous_in_aggregate
      evidence_type: string
```

---

## 5. Changes to existing tools

`get_indicators` gains an optional `include_observations` parameter (default true in v3.0 — by this stage, observations are part of the value proposition).

When observations are included, the result distinguishes them clearly:

```yaml
results:
  - place_id: "ltla24:E06000004"
    indicator: "housing.affordability"
    value: 7.2
    unit: "ratio"
    period: "2023"
    source: SourceRef               # ONS
    confidence: "official"
    related_observations:
      - observation_id: uuid
        claim_statement: "Local landlords increasingly refusing tenants on benefits."
        organisation_name: "Example Housing Aid"
        evidence_type: "qualitative"
        period: "2025-Q3"
        confidence: "experiential"
```

`get_narrative_brief` and `compose_dashboard` gain explicit handling of observations: dedicated sections or panels for *what local organisations are seeing*, distinct from official statistics. Citations always lead back to the observation record and the publishing organisation.

`get_place_profile` gains an `observations_summary` block listing recent observations grouped by theme.

---

## 6. The observation as part of the corpus

The questions corpus from v1 captures the demand side. In v3, it expands to also reference the supply side:

```yaml
QuestionRecord:
  # ... all v1 + v1.5 fields ...

  # v3 additions
  observations_used: [uuid]       # observation_ids cited in any composed artefact
```

This closes a loop: every brief or dashboard that uses a contributed observation links back to it. Organisations can see how their observations have been used. Funders and commissioners can see what local insight is most often cited.

---

## 7. Quality, signal, moderation

Three mechanisms keep the contribution layer trustworthy.

### 7.1 Schema validation

Hard rules at submission time. Place IDs must resolve. Periods must be sane. Required fields present. Themes must be drawn from a controlled list (extensible via RFC). This filters out 90% of accidental noise before it ever reaches the corpus.

### 7.2 Reputation signal

Each context source accrues a lightweight reputation signal based on:

- Time since first verified profile.
- Number and consistency of submissions.
- Cross-citations with other context sources on similar themes/places.
- Editorial flags raised and resolved.

The reputation signal is **never** used to block consumers from seeing an observation. It is used to:

- Order observations within a result set when many are returned.
- Determine which submissions go to editorial review vs. auto-accept.
- Surface organisations whose observations are widely corroborated.

The signal is published transparently per organisation. There is no secret scoring.

### 7.3 Editorial review

A small editorial board (initially Tom + a small number of trusted external editors) reviews:

- First-three submissions from any new context source.
- Submissions flagged by the reputation signal.
- Submissions reported by other users.
- Schema or theme RFCs.

Editorial decisions are public and recorded with rationale. Organisations whose submissions are rejected can appeal in writing.

---

## 8. Authentication

v3 requires authenticated submission. Authentication extends the v2 magic-link mechanism with role-based permissions:

- **Submitter** — can create new observations on behalf of the organisation.
- **Steward** — submitter rights plus profile management and ability to withdraw observations.
- **Auditor** (read-only) — can see historical and superseded records, including non-public attribution.

A single individual can hold roles across multiple organisations.

---

## 9. UI changes

- **`/contribute`** — landing page for organisations interested in submitting observations. Onboarding flow checks for a v2 profile, walks through schema, offers a guided composer.
- **`/observations`** — public stream of recent observations across the system. Filterable by place and theme.
- **`/observations/{id}`** — single observation viewer with full provenance, the claim, the evidence, and any briefs or dashboards that have cited it.
- **`/orgs/{context_source_id}/observations`** — all observations from a given organisation. Pre-existing in v2 as a placeholder; populated in v3.
- **`/place/{id}`** — gains an "Observations from local organisations" section.
- **`/asks/gaps`** — the gap analysis view from v1.5 now also surfaces *gaps where observations exist but no official data does* — a strategically interesting inversion.

---

## 10. Migration from the original databank

A migration tool ingests the original MPC Local Needs Data Bank's translatable observations and lifts them into the v3 schema:

- Each contributing organisation in the old databank is matched (or asked to publish) a v2 context profile.
- Each historical observation is inserted with `submitted_at` set to the original submission date and a `methodology_note` indicating it was migrated.
- Where no v2 profile exists for a contributing organisation, observations are imported but kept private until the profile is published.

This is a one-off operation. The migration tool is published as part of v3.

---

## 11. Out of scope for v3

- Real-time streaming observations (e.g. ingesting case management system events directly). Worth a future v3.1, but introduces complexity around consent and PII that v3 doesn't take on.
- Automatic signal detection across observations (e.g. "five organisations in adjacent LTLAs report the same thing — flag as a signal"). The data shape supports it, but the algorithm and presentation deserve their own version.
- Funder dashboards built on observations. Will likely emerge as a third-party use of the API rather than a Soundings feature.
- Closed-network observations (organisations sharing observations only with named partners). A useful future direction but breaks the open-by-default model that v3 establishes first.

---

## 12. Open questions

1. **Theme controlled vocabulary.** The list of themes is the most contested piece of governance. Start small — maybe twelve themes — and let the editorial process expand them. RFC process needed.
2. **Aggregation rules for `aggregated_only` attribution.** When an organisation chooses not to be named publicly but allows their observation to inform aggregates, how is the threshold for "safe to publish in aggregate" determined? Likely a minimum of three contributing organisations per place + theme combination.
3. **PII risk in qualitative excerpts.** Even with sanitisation, qualitative excerpts carry risk. Worth a published guidance document for organisations and a default rejection of any excerpt over a length threshold without explicit confirmation of consent.
4. **API for third-party observation submission.** Should observations be submittable via API as well as via UI? Probably yes for v3.1 — but auth and rate-limiting need careful design.
5. **Withdrawn observation visibility.** Withdrawals hide from current results, but the corpus historian wants to know *that* something was withdrawn (not *what*). What's the right balance?

---

## 13. Build sequence (6–8 weeks on top of v2)

| Phase | Weeks | Deliverable |
|---|---|---|
| 1 | 1 | Observation schema, validation, theme controlled list. |
| 2 | 1–2 | Submission tool, basic auto-accept logic, `submit_observation` and `get_observations` tools. |
| 3 | 1 | Reputation signal, editorial review queue, audit trail. |
| 4 | 1 | Existing tools extended (`get_indicators`, briefs, dashboards) to surface observations clearly distinguished from official data. |
| 5 | 1 | UI for `/contribute`, `/observations`, single observation viewer, organisation observation listings. |
| 6 | 1 | Migration tool from original MPC databank. |
| 7 | 1 | First cohort of 10–20 contributing organisations onboarded; documentation; v3 launch. |

---

## End of spec set

This is the final document in the Soundings v1–v3 spec set. The system at the end of v3 delivers the full original vision: open data fabric (v1), human-friendly interfaces (v1.5), federated organisational context (v2), and structured contributions (v3) — all with consistent provenance, all locally hostable, all open.

Beyond v3 lies the work of growing the network: more publishing organisations, more upstream sources, deeper integration with adjacent open standards (Open Referral UK / HSDS, 360Giving, Murmurations, Open Org Standard), and possibly the cross-place signal detection that the data shape now supports.

But that's a different conversation. This one ends here.

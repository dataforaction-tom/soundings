# Soundings v2 — Context layer

**Status:** Draft 0.1
**Scope:** Organisations publish lightweight machine-readable profiles describing who they are, where they work, and what they observe. Soundings indexes these and treats them as first-class sources alongside ONS, DWP, etc.
**Builds on:** [v1](./v1-orchestration-and-capture.md), [v1.5](./v1.5-just-in-time-interfaces.md)
**Related:** [README](../README.md) · [v3](./v3-contribution-layer.md)

---

## 1. Purpose

Until v2, every source in Soundings is a public dataset. v2 introduces a second kind of source: organisations themselves.

An organisational context profile says, in machine-readable form: *we are this organisation, we work in these places, we see these kinds of need, here's our methodology, here's how recent and confident our information is.* These profiles are published by the organisation under their own domain, indexed by Soundings, and join the same provenance system as ONS data.

This is the layer that lets a brief or a dashboard say things like *"according to a refugee-support organisation working in Stockton, the most-mentioned barrier in the last quarter was housing"* alongside *"DWP data shows X claimants in Stockton in Q3 2025"* — with both clearly attributed and weighted.

v2 does not yet allow organisations to submit numeric observations. That's [v3](./v3-contribution-layer.md). v2 establishes who they are; v3 lets them speak.

---

## 2. Design intent

This builds directly on the [llmstxt.social](https://llmstxt.social/) pattern Tom built for The Good Ship — organisations publish a small, well-structured machine-readable file at a known location on their own site, and a public index makes it findable. Soundings extends that pattern with a needs-specific schema.

The principles are deliberate:

- **Self-sovereign.** Organisations host their own profiles. Soundings indexes; it does not own.
- **Voluntary and free.** No paywall, no required registration to publish. The barrier to participation is one file at a known URL.
- **Lightweight.** A starter profile should take an hour to write. Rich profiles should be possible but never required.
- **Built on existing standards.** Where there's already a way to express something (HSDS for services, 360Giving for grants, ICNPO for classification), use it.
- **Composable with the [Open Org Standard](https://github.com/tomcwatson/open-org-standard).** Profiles SHOULD be a superset of an Open Org Standard organisational profile, with needs-specific extensions.

---

## 3. The profile

Each contributing organisation publishes a file at a well-known location on their own site:

```
https://example-org.uk/.well-known/soundings.yaml
```

(`yaml` for human authoring; `.json` is also valid. Both produce identical canonical JSON when parsed.)

### 3.1 Schema (v2.0)

```yaml
soundings_version: "2.0"

organisation:
  name: "Example Refugee Support"
  legal_form: "registered_charity"
  identifiers:
    charity_commission: "1234567"
    companies_house: "12345678"
  url: "https://example-org.uk/"
  description: "We support people seeking asylum across Teesside."
  classification: ["icnpo:7100"]   # Civic and Advocacy

geography:
  primary_places:
    - "ltla24:E06000004"           # Stockton-on-Tees
    - "ltla24:E06000005"           # Darlington
  reach_description: "We work across Teesside but receive referrals from across the North East."

what_we_observe:
  - theme: "housing"
    description: "Barriers to securing safe housing for asylum-seekers."
    evidence_types: ["case_notes", "service_user_interviews"]
    cadence: "ongoing"
    recency: "current"
  - theme: "mental_health"
    description: "Patterns in mental health support needs."
    evidence_types: ["case_notes", "outcome_measures"]
    cadence: "quarterly"
    recency: "Q3 2025"

methodology:
  collection: "Case notes recorded by support workers; quarterly review by the head of services."
  sample: "Every active client is included in case-note analysis."
  caveats:
    - "We see only people who have approached us; not a representative sample of need."

publishing_cadence: "quarterly"
last_reviewed: "2025-09-30"

contact:
  for_data_questions:
    name: "Jane Doe"
    role: "Head of Services"
    # No email in the public profile by default.

licence: "CC-BY-4.0"
```

### 3.2 Required vs optional fields

Required: `soundings_version`, `organisation.name`, `organisation.url`, `geography.primary_places`, `licence`, `last_reviewed`.

Everything else is optional. A minimal profile is genuinely small.

### 3.3 Identifiers and verification

Where a charity_commission or companies_house identifier is given, Soundings cross-checks against the public registers at index time. Mismatches are flagged in the index, not silently corrected.

Soundings does not require organisations to be registered charities or companies. Other models — community-run groups, mutual aid networks, informal collectives — can publish profiles without statutory identifiers.

### 3.4 Versioning

The schema is versioned. Soundings indexes the latest published version of each profile but retains historical snapshots for the corpus. Schema upgrades are additive within a major version.

---

## 4. The index

Soundings runs a public index of context profiles.

### 4.1 Discovery

Three ways an organisation gets indexed:

1. **Direct submission.** A `POST /index/submit` endpoint accepting a profile URL. Soundings fetches, validates, and adds.
2. **Crawl from related sources.** When `find_organisations_in_place` returns an organisation, Soundings checks whether it has a `/.well-known/soundings.yaml` and indexes if found.
3. **Index federation.** Other indexes can publish their own list; Soundings can pull from them. This is how the system stays open — there is no single index of record.

### 4.2 Index entry

Each indexed profile produces an internal record:

```yaml
ContextSourceRecord:
  source_id: string              # generated, e.g. "ctx.example_refugee_support"
  profile_url: string
  organisation_name: string
  identifiers: object
  geography_primary_places: [string]
  themes: [string]
  last_fetched: ISO8601
  last_reviewed_self_reported: ISO8601
  fetch_status: "ok" | "stale" | "error" | "removed"
  signature: string | null       # for v2.1, see §7
```

A `source_id` for an organisational source uses the prefix `ctx.` to clearly distinguish from official sources.

### 4.3 Refresh policy

- Profiles are refetched on a cadence proportional to their declared `publishing_cadence`, capped at weekly minimum and quarterly maximum.
- An organisation can ping `POST /index/refresh?url=...` to request immediate re-fetch.
- Profiles that 404 for more than 30 days are marked `removed` and excluded from query results, but kept in the historical corpus.

---

## 5. New tools

### 5.1 `find_organisations_with_context`

Like v1's `find_organisations_in_place`, but only returns organisations with indexed Soundings profiles.

```yaml
input:
  place_id: string
  themes: [string] | optional
  recency: "current" | "12m" | "any" | optional
output:
  organisations:
    - context_source_id: string  # "ctx.example_refugee_support"
      organisation_name: string
      profile_url: string
      identifiers: object
      themes: [string]
      last_reviewed: ISO8601
      observations_summary:        # parsed from what_we_observe in the profile
        - theme: string
          description: string
          recency: string
```

### 5.2 `get_context_profile`

Fetch a full parsed profile by `context_source_id`.

```yaml
input:
  context_source_id: string
output:
  profile: object               # the full parsed profile
  source_ref: SourceRef         # with the organisation as publisher
  fetch_status: string
  signature_verified: boolean | null
```

---

## 6. Changes to existing tools

`get_place_profile`, `get_indicators`, `get_narrative_brief`, and `compose_dashboard` all gain an optional `include_context_sources` parameter (default false in v2.0, may flip to true in a later version once trust patterns are established).

When set, briefs and dashboards may quote from organisational profiles in addition to official statistics, with the `confidence` field on indicators set to `"qualitative"` and the source clearly attributed in citations.

In briefs, qualitative context appears in clearly-marked sections — never blended with quantitative claims as if equivalent.

---

## 7. Trust and signing (v2.1, deferred)

A future v2.1 introduces optional signing of profiles. An organisation can sign their `soundings.yaml` with a key, publish the public key at a `/.well-known` location, and Soundings will verify the signature at index time. This protects against profile tampering and gives consumers a cryptographic chain back to the publishing organisation.

v2.0 ships without signing. The trust model in v2.0 is "we fetched it from the URL the organisation says is theirs, we cross-check identifiers where given, and we surface fetch metadata transparently". That's enough to start. Signing is additive and does not change the schema.

---

## 8. Authentication

v2 introduces optional authentication for organisations who want to:

- Publish a profile via the Soundings UI rather than self-hosting (with the file generated and hostable elsewhere later).
- Manage their indexed profile (request re-fetch, mark as superseded, etc.).
- Get higher rate limits on brief and dashboard generation.

Authentication uses email-based magic links in v2.0. No passwords. No SSO yet.

Organisations remain identified by their published profile, not by their Soundings account. Accounts are conveniences, not identities.

---

## 9. UI changes

- **`/orgs`** — new. Browse the index. Filter by place, by theme, by recency.
- **`/orgs/{context_source_id}`** — public profile viewer. Shows the organisation's stated geography, themes, methodology, and a feed of any observations they've shared (the latter is empty until v3).
- **`/orgs/{context_source_id}/asks`** — the questions corpus filtered to questions where this organisation's profile was cited. Useful for the organisation themselves.
- **`/publish`** — a guide and authoring helper for organisations new to publishing a profile. Generates a starter `soundings.yaml` from a short form.

The home `/` text box gains a "Include organisational context" toggle, defaulting off in v2.0 and to be reviewed for v2.1.

---

## 10. Out of scope for v2

- Numerical observations from organisations (deferred to [v3](./v3-contribution-layer.md)).
- Profile signing and verification (deferred to v2.1).
- Single sign-on or federated authentication.
- Org-to-org messaging or collaboration features.
- Any change to the v1 tool contracts.

---

## 11. Open questions

1. **Schema governance.** Once v2 ships, schema changes affect every publisher. RFC process? Editorial board? Likely the same body as governs the indicator catalogue.
2. **Index trust.** Federating with other indexes is the right principle, but creates operational questions: how do we handle disputed identities, duplicate profiles, malicious submissions? Probably needs a published moderation policy.
3. **Relationship to Open Org Standard.** Soundings profiles should be a superset of OOS profiles where they overlap. Worth a joint design pass once OOS is more concrete.
4. **Onboarding pipeline.** What's the most efficient way to get the first 50–100 profiles published? Likely targeted outreach via existing Good Ship and TechFreedom networks.

---

## 12. Build sequence (4–5 weeks on top of v1.5)

| Phase | Weeks | Deliverable |
|---|---|---|
| 1 | 1 | Schema spec, validation tooling, `/.well-known/soundings.yaml` fetcher and parser. |
| 2 | 1 | Index tables in Postgres, submission and refresh endpoints, federation pull mechanism. |
| 3 | 1 | `find_organisations_with_context`, `get_context_profile` tools. Briefs and dashboards extended to optionally include qualitative context. |
| 4 | 1 | `/orgs` UI, `/publish` authoring helper, magic-link auth. |
| 5 | 1 | Targeted onboarding of 10–20 friendly first publishers; documentation; soft launch. |

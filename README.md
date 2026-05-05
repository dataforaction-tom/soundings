# Soundings

> *Taking the measure of local need.*

An open insight commons for understanding what's happening in places across the UK. Built as infrastructure, not a product. Designed to be hosted by anyone, used by humans and LLMs alike, and grown additively over time.

## What it is

A single MCP server wraps the messy patchwork of UK open data behind a small set of question-shaped tools. Anyone — a charity worker, a funder, a commissioner, an LLM agent — can ask coherent questions about a place and get answers with sources attached. Every question asked becomes part of a published, consented corpus, turning the demand side of local insight into a public dataset in its own right.

In nautical use, a *sounding* is what you take to understand the depth and shape of unfamiliar water. The name carries that, plus a quieter sense of voices being heard. Each query to the system is a sounding. The published corpus is the soundings record.

## Why this set of docs

Soundings is sequenced into four specs. Each is independently buildable. Each builds on the last without breaking what came before.

| Spec | What it adds | Status |
|---|---|---|
| [v1 — Orchestration & Capture](./v1-orchestration-and-capture.md) | The MCP server with six question-shaped tools wrapping ~10 UK open data sources, plus the consented questions corpus. Locally hostable on a single machine. | Specified |
| [v1.5 — Just-in-time interfaces](./v1.5-just-in-time-interfaces.md) | Glimpse-style on-demand dashboards, narrative briefs as a server-side capability, and the public `/asks` corpus view. | Specified |
| [v2 — Context layer](./v2-context-layer.md) | Organisations publish lightweight machine-readable profiles describing who they are, where they work, and what they observe. Soundings indexes these and treats them as first-class sources alongside ONS, DWP, etc. | Specified |
| [v3 — Contribution layer](./v3-contribution-layer.md) | Organisations submit structured observations — claims about local need backed by evidence — that sit alongside official statistics in answers, clearly flagged and provenanced. | Specified |

Read in order if you're new. Skip to the version you're working on if you're building.

Working artefacts referenced by the specs live alongside:

- [`catalogue/indicators.yaml`](./catalogue/indicators.yaml) — the v1 indicator catalogue. The contract between the server and consumers. New indicators are additive.
- [`examples/soundings.yaml`](./examples/soundings.yaml) — a fully-worked, annotated example of a v2 context profile.
- [`examples/soundings-minimal.yaml`](./examples/soundings-minimal.yaml) — the smallest valid context profile, for organisations starting out.

## Design principles (apply across all versions)

- **Infrastructure over product.** The MCP server is the thing. Reference UI is thin and exists to demonstrate, not to lock people in.
- **Question-shaped, not dataset-shaped.** Tools are organised by what people want to know, not by which API a fact came from.
- **Geography-first.** Every answer is anchored to a place identifier from a single canonical spine. Boundary changes are handled at the orchestration layer.
- **Provenance everywhere.** Every value carries its source, the date it was published, and the date it was retrieved. No silent aggregation.
- **Open by default.** Code, schema, and the questions corpus are openly licensed. The hosted reference instance is one of many possible deployments.
- **Transparent capture.** Logging the questions corpus is a visible part of the contract with users, not a hidden side effect.
- **Locally hostable.** The whole stack runs on a single machine. Scale-out is possible but never required.
- **Additive growth.** Later versions add tools and sources. They do not change the contracts established in v1.

## Build context

Initial deployment target: a Mac mini in North East England, running locally. The architecture is sized for that. If Soundings finds an audience, it can move to a more durable host without code changes — the constraint is operational, not architectural.

Maintained under [The Good Ship](https://good-ship.co.uk/). Sits alongside Contour (outdoor advisory) and Shipyard (AI tooling) as part of the wider Good Ship offer.

## Status

Drafts. Not yet built. Comments, RFCs, and pull requests welcome once the repo is up.

## Licence

All specs CC BY 4.0. Code (when published) AGPL-3.0 for the server, CC0 for the schema and indicator catalogue.

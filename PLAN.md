# Plan

> Last updated: 2026-05-10
> Status: **Phase 0 complete.** Tag `v0.1.0-phase-0`.

## Objective

Build Soundings v1 — a single MCP server wrapping a curated set of UK open
data sources behind a small set of question-shaped tools, with every consented
question logged to a public corpus. v1 is sequenced into ~6 phases over
roughly 10–12 weeks per the build plan in `docs/v1-orchestration-and-capture.md` §13.

## Approach

Per-phase plans live in `docs/plans/`:

- `docs/plans/2026-05-05-soundings-v1-design.md` — implementation design.
- `docs/plans/2026-05-05-soundings-v1-phase-0-plan.md` — Phase 0 plan (40 tasks).

Each phase plan is TDD task-by-task: failing test → minimum implementation →
green → conventional-commit. Block-level commit boundaries.

## Tasks

- [x] Phase 0 — Repo scaffolding, schema, geography spine. Acceptance:
      `test_phase_0_e2e.py` resolves a postcode to all 8 geography levels
      via the integration suite. **Done; tag `v0.1.0-phase-0`.**
- [ ] Phase 1 — Adapters for ONS Census 2021 (Nomis), MHCLG IMD; first
      three MCP tools (`find_place`, `get_place_profile`, `get_indicators`)
      over HTTP and MCP transports. Plan: TBD as
      `docs/plans/<date>-soundings-v1-phase-1-plan.md`.
- [ ] Phase 2 — Capture pipeline + sanitisation + minimal `/` and
      `/place/{id}` UI.
- [ ] Phase 3 — Adapters for Fingertips, DWP Stat-Xplore, DfE, police.uk;
      `compare_places` and `get_trend`.
- [ ] Phase 4 — Adapters for Charity Commission, 360Giving, Find That Charity;
      `find_organisations_in_place`.
- [ ] Phase 5 — First monthly corpus release, doc pass.
- [ ] Phase 6 — Public soft launch on the Mac mini.

## Decisions Made

| Decision | Rationale | Date |
|----------|-----------|------|
| Compose ports 5433 / 8001 | Avoid local conflict with another stack on 5432 / 8000. | 2026-05-09 |
| sources.yaml aligned to indicators.yaml IDs | The catalogue is the contract; sources must cover everything it references. | 2026-05-09 |
| BUC fallback chain BUC → BSC → BGC → BFC | Several layers don't publish BUC. Smallest available wins for v1's outline-only display. | 2026-05-10 |
| `httpx.MockTransport` instead of `pytest-vcr` cassettes | Some OGP service URLs are unverified — re-recording cassettes on every URL fix would loop. Live verification runs nightly. | 2026-05-10 |
| Local git identity = `Tom Watson <tom@good-ship.co.uk>` | Matches active session email. | 2026-05-09 |

## Open Questions

- [ ] OGP service URLs in `docs/adr/0001-geography-data-sources.md` marked
      `(unverified)` — confirm against the live portal at first seed.
- [ ] LTLA-filter for `make seed-light` — currently it skips the heavy
      LSOA/MSOA layers; might want a true single-LTLA filter for finer dev loops.

## Out of Scope

- Phase 1+ work — separate plan documents.
- Anything in v1.5/v2/v3 — separate spec docs.

# Plan

> Last updated: 2026-05-17 (session 6)
> Status: **Phase 4 in progress.** Block C (Find That Charity) — Tasks 15-18
> complete. Blocks D–F pending.

## Objective

Build Soundings v1 — a single MCP server wrapping a curated set of UK open
data sources behind a small set of question-shaped tools, with every consented
question logged to a public corpus. v1 is sequenced into ~6 phases over
roughly 10–12 weeks per the build plan in `docs/v1-orchestration-and-capture.md` §13.

## Approach

Per-phase plans live in `docs/plans/`:

- `docs/plans/2026-05-05-soundings-v1-design.md` — implementation design.
- `docs/plans/2026-05-05-soundings-v1-phase-0-plan.md` — Phase 0 plan (40 tasks).
- `docs/plans/2026-05-10-soundings-v1-phase-1-plan.md` — Phase 1 plan (52 tasks).
- `docs/plans/2026-05-11-soundings-v1-phase-2-plan.md` — Phase 2 plan (45 tasks).
- `docs/plans/2026-05-11-soundings-v1-phase-3-plan.md` — Phase 3 plan (45 tasks).

Each phase plan is TDD task-by-task: failing test → minimum implementation →
green → conventional-commit. Block-level commit boundaries. From Phase 3 Block E
onwards each block lands as a single squash-merged PR rather than direct commits
to `main`.

## Tasks

- [x] Phase 0 — Repo scaffolding, schema, geography spine.
      Tag `v0.1.0-phase-0`.
- [x] Phase 1 — Three indicator adapters (MYE, Census, IMD); three tools
      (`find_place`, `get_indicators`, `get_place_profile`); HTTP + MCP
      transports; loader daemon. Tag `v0.2.0-phase-1`.
- [x] Phase 2 — Capture pipeline (raw + sanitised, two-step write), six
      sanitisation rules, monthly publication, minimal Astro UI (`/`,
      `/place/[id]`, `/about`), Resend alerts. Tag `v0.3.0-phase-2`.
- [x] Phase 3 — Adapters for Fingertips, DWP Stat-Xplore, DfE, police.uk,
      ONS APS; `compare_places` and `get_trend` tools; UI sparklines on
      `/place/[id]` and a new `/compare` page. Tag `v0.4.0-phase-3`
      pending browser smoke.
- [x] Phase 4 — Adapters for Charity Commission (loader; bulk register),
      360Giving + Find That Charity (passthrough);
      `find_organisations_in_place`. **Blocks 0, A, B, C landed**;
      Blocks D, E, F pending.
- [ ] Phase 5 — First monthly corpus release, doc pass.
- [ ] Phase 6 — Public soft launch on the Mac mini.

## Decisions Made

| Decision | Rationale | Date |
|----------|-----------|------|
| Compose ports 5433 / 8001 | Avoid local conflict with another stack on 5432 / 8000. | 2026-05-09 |
| sources.yaml aligned to indicators.yaml IDs | The catalogue is the contract; sources must cover everything it references. | 2026-05-09 |
| BUC fallback chain BUC → BSC → BGC → BFC | Several layers don't publish BUC. Smallest available wins for v1's outline-only display. | 2026-05-10 |
| `httpx.MockTransport` instead of `pytest-vcr` cassettes | Some upstream service URLs/codes are unverified — re-recording cassettes on every URL fix would loop. Live verification runs nightly. | 2026-05-10 |
| Loader runs as a separate `loader` Docker service | Per design §6. Server serves reads, loader runs APScheduler against `refresh_cadence`. Same image, different command. | 2026-05-10 |
| MCP transport via `FastMCP.sse_app()` mounted on FastAPI | Single ASGI process, no separate stdio supervisor. Same tool handlers as the HTTP routes; MCP module is registration boilerplate only. | 2026-05-10 |
| `cache_status` window estimated from cron via `_cron_to_window_days` | Avoids a new dep; falls back to 30 days for unrecognised patterns. Good enough for v1. | 2026-05-10 |
| Local git identity = `Tom Watson <tom@good-ship.co.uk>` | Matches active session email. | 2026-05-09 |
| IMD 2025 + IMD 2019 as parallel sources (`mhclg.imd2025`, `mhclg.imd2019`) | Both editions are useful; 2019 is the established baseline, 2025 is the new release. `fetch_indicator(period=None)` returns latest (2025) by default. Subclassing reuses the parser/loader logic. | 2026-05-11 |
| IMD 2025 uses File 5 (Scores), IMD 2019 uses File 2 | MHCLG restructured the 2025 release: raw scores moved out of File 2 (now rank/decile only) into File 5. IMD 2019 still has scores + deciles in File 2. | 2026-05-11 |
| IMD loader pre-filters rows by existing `geography.place` ids | Avoids FK violations during partial seeds (`make seed-light`) and absorbs minor LSOA boundary version mismatches between IMD editions and our geography spine. | 2026-05-11 |
| `compare_places` defaults `comparison_basis="percentile"` | Spec §4.4 leaves the default open; percentile against same-type peers is the most useful "how does my place compare?" framing for downstream LLMs. | 2026-05-12 |
| Passthrough peer-universe fan-out has soft budget 200 | Compare_places against >200 peers via real upstream calls is wasteful and slow; instead, rank only the caller's slice with a `BUDGET_CAVEAT` so the methodology is explicit. | 2026-05-12 |
| `series_break:` prefix on catalogue caveats | Phase 3 plan Task 2 convention: the prefix partitions caveats into `Trend.breaks_in_series` (prefix stripped) vs the regular caveats list on the response. | 2026-05-12 |
| Police.uk methodology caveat asserted verbatim by adapter test | Centroid-proximate aggregation undercounts large or dispersed LTLAs; a refactor that drops the caveat would silently degrade provenance, so the test pins the exact string. | 2026-05-12 |
| UI uses `linkedom` for SSR DOM polyfill | `@observablehq/plot` calls `document.createElement` internally; Node SSR has no native `document`. linkedom is lighter than jsdom and ships a spec-shaped DOM that Plot is happy with. | 2026-05-12 |
| Phase 3 Block E onwards lands as squash-merged PRs | First three phases shipped as direct commits to `main`. From PR #1 onwards each block of Phase 3 is a feature branch + squashed PR — matches the global "always work on a branch" rule. | 2026-05-12 |

## Open Questions

- [ ] OGP service URLs in `docs/adr/0001-geography-data-sources.md` marked
      `(unverified)` — confirm against the live portal at first seed.
- [x] Nomis dataset/measure/cell codes in `catalogue/nomis-mapping.yaml`
      ~~confirm against real API~~ — verified for `population.total` (MYE),
      `population.households.lone_parent_share` (Census), and
      `economy.employment_rate` (APS, NM_17_5 variable 45) via live tests.
      Other Census TS-table dataset IDs (ethnic group, qualifications,
      tenure) and the ONS APS pay + affordability codes are pinned with
      plausible IDs but only exercised at first integration test or tool use.
- [x] IMD 2025 download URL in ADR-0002 — ~~confirm or fall back to 2019~~
      verified live 2026-05-11.
- [ ] IMD 2025 deciles — File 2 (deciles/ranks) is not currently loaded for
      the 2025 edition.
- [ ] LTLA-filter for `make seed-light` — currently filters MYE+Census by
      place_filter; geography spine still loads full layers (minus LSOA/MSOA
      in light mode).
- [ ] Nomis `value_scale` is currently only wired into the Census + APS
      adapters. MYE doesn't need it for `population.total` (count). When a
      future MYE indicator uses `measures=20301` (percent) it'll need the
      same treatment — extract a shared helper at that point.
- [x] **Fingertips data endpoint pattern (Phase 3 Task 11)** — resolved
      2026-05-11.
- [ ] Stat-Xplore cube IDs in `catalogue/statxplore-mapping.yaml` are
      plausible-but-unverified; auth-gated schema. Live test will iterate
      once `STATXPLORE_API_KEY` is added to GitHub Actions Secrets.
- [ ] DfE EES KS4 + persistent absence dataset/indicator UUIDs are
      placeholders; only FSM is real. Live test fails-closed nightly until
      they're discovered.
- [ ] Nomis APS median pay (NM_30_1) + affordability ratio (NM_173_1)
      field codes haven't been live-discovered — employment / unemployment
      use the verified NM_17_5 path. When these indicators get exercised,
      mirror the NM_17_5 discovery (probe `.def.sdmx.json` to find the
      variable + measure codes).
- [ ] Police.uk `crime.violence_rate` and `crime.asb_rate` haven't been
      live-tested individually. Category slugs are stable but a smoke run
      before the Phase 3 tag would be sensible.

## Out of Scope

- Phase 4+ work — separate plan documents.
- Anything in v1.5/v2/v3 — separate spec docs.

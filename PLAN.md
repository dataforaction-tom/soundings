# Plan

> Last updated: 2026-05-11
> Status: **Phase 2 complete.** Tag `v0.3.0-phase-2`. Capture pipeline,
> sanitisation rules, monthly publication, and minimal Astro UI all live.

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

Each phase plan is TDD task-by-task: failing test → minimum implementation →
green → conventional-commit. Block-level commit boundaries.

## Tasks

- [x] Phase 0 — Repo scaffolding, schema, geography spine.
      Tag `v0.1.0-phase-0`.
- [x] Phase 1 — Three indicator adapters (MYE, Census, IMD); three tools
      (`find_place`, `get_indicators`, `get_place_profile`); HTTP + MCP
      transports; loader daemon. Tag `v0.2.0-phase-1`.
- [x] Phase 2 — Capture pipeline (raw + sanitised, two-step write), six
      sanitisation rules, monthly publication, minimal Astro UI (`/`,
      `/place/[id]`, `/about`), Resend alerts. Tag `v0.3.0-phase-2`.
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
| `httpx.MockTransport` instead of `pytest-vcr` cassettes | Some upstream service URLs/codes are unverified — re-recording cassettes on every URL fix would loop. Live verification runs nightly. | 2026-05-10 |
| Loader runs as a separate `loader` Docker service | Per design §6. Server serves reads, loader runs APScheduler against `refresh_cadence`. Same image, different command. | 2026-05-10 |
| MCP transport via `FastMCP.sse_app()` mounted on FastAPI | Single ASGI process, no separate stdio supervisor. Same tool handlers as the HTTP routes; MCP module is registration boilerplate only. | 2026-05-10 |
| `cache_status` window estimated from cron via `_cron_to_window_days` | Avoids a new dep; falls back to 30 days for unrecognised patterns. Good enough for v1. | 2026-05-10 |
| Local git identity = `Tom Watson <tom@good-ship.co.uk>` | Matches active session email. | 2026-05-09 |
| IMD 2025 + IMD 2019 as parallel sources (`mhclg.imd2025`, `mhclg.imd2019`) | Both editions are useful; 2019 is the established baseline, 2025 is the new release. `fetch_indicator(period=None)` returns latest (2025) by default. Subclassing reuses the parser/loader logic. | 2026-05-11 |
| IMD 2025 uses File 5 (Scores), IMD 2019 uses File 2 | MHCLG restructured the 2025 release: raw scores moved out of File 2 (now rank/decile only) into File 5. IMD 2019 still has scores + deciles in File 2. | 2026-05-11 |
| IMD loader pre-filters rows by existing `geography.place` ids | Avoids FK violations during partial seeds (`make seed-light`) and absorbs minor LSOA boundary version mismatches between IMD editions and our geography spine. | 2026-05-11 |

## Open Questions

- [ ] OGP service URLs in `docs/adr/0001-geography-data-sources.md` marked
      `(unverified)` — confirm against the live portal at first seed.
- [x] Nomis dataset/measure/cell codes in `catalogue/nomis-mapping.yaml`
      ~~confirm against real API~~ — verified for `population.total` (MYE)
      and `population.households.lone_parent_share` (Census) via live tests
      2026-05-11. Other Census TS-table dataset IDs (ethnic group,
      qualifications, tenure, etc.) are pinned with plausible IDs but only
      exercised at first integration test or tool use.
- [x] IMD 2025 download URL in ADR-0002 — ~~confirm or fall back to 2019~~
      verified live 2026-05-11; switched 2025 to File 5 (Scores) and added
      `mhclg.imd2019` as a sibling source loading from IMD 2019 File 2.
- [ ] IMD 2025 deciles — File 2 (deciles/ranks) is not currently loaded for
      the 2025 edition. Either add a second download in the 2025 loader or
      switch indicator contracts to use ranks/deciles where MHCLG no longer
      publishes raw scores in the top-level files.
- [ ] LTLA-filter for `make seed-light` — currently filters MYE+Census by
      place_filter; geography spine still loads full layers (minus LSOA/MSOA
      in light mode).
- [ ] Nomis `value_scale` is currently only wired into the Census loader.
      MYE doesn't need it for `population.total` (count). If a future MYE
      indicator uses `measures=20301` (percent) it'll need the same
      treatment — extract a shared helper at that point, not pre-emptively.
- [ ] **Fingertips data endpoint pattern (Phase 3 Task 11)** — the
      `/api/all_data/json/by_indicator_id` endpoint our adapter targets
      currently 500s. The working data endpoint appears to be
      `/api/latest_data/all_indicators_in_profile_group_for_child_areas`,
      which requires `profile_id` + `group_id` per query (one indicator
      can live in multiple profile/group combinations).
      `catalogue/fingertips-mapping.yaml` needs `profile_id` + `group_id`
      per entry; client `get_indicator_data` must rewrite to target the
      working endpoint; live test `tests/live/test_fingertips_live.py`
      is currently skipped pending this. The adapter scaffolding,
      mapping, and registry registration are in place — just the URL
      pattern needs verification + a mapping schema bump.

## Out of Scope

- Phase 2+ work — separate plan documents.
- Anything in v1.5/v2/v3 — separate spec docs.

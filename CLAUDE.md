# Project: Soundings

An open insight commons for understanding UK places. Single MCP server wrapping UK open data (population, health, crime, civil society) behind question-shaped tools, with every consented question logged to a public corpus.

## Architecture

- `server/` — FastAPI + MCP server, Python 3.12
- `ui/` — Astro 4, server-rendered
- `infra/` — Docker Compose (Postgres + PostGIS 16)
- `catalogue/` — indicators.yaml + sources.yaml

## Commands

- `make up` — Start dev stack
- `make migrate` — Apply DB migrations
- `make seed` — Full seed (~15 min)
- `make seed-light` — Light seed (~5 min, single LTLA)
- `make test` — Run Python tests
- `make publish-corpus` — Generate monthly corpus release

## Standards

- Conventional commits (`feat`, `fix`, `test`, `docs`, `chore`)
- TDD: failing test → minimum implementation → green → commit
- One feature branch per block, squash-merged PRs
- All tests must pass before merging

## Verification

- Run `make test` before considering any task complete
- Run `make up && make seed-light` for local smoke test
- Check lint with pre-commit hooks

## Working Rules

- Check for existing patterns before creating new ones
- Prefer small, incremental changes
- If a task will take >50 lines, use plan mode first
- Don't add dependencies without asking
- Don't refactor code that wasn't part of the task

## State & Progress

> Updated: 2026-05-24
> Phase: **5 in progress** — first monthly corpus release + doc pass
> Status: Phase 0–4 shipped, Phase 5 running

See PLAN.md for task tracking, STATE.md for system state.

## Known Issues

- Geography chain tests updated for ONS LSOA→LTLA lookup (no MSOA layer)
- Some live tests depend on API keys (Stat-Xplore)

## Lessons Learned

- ONS simplified LSOA→LTLA lookup: no MSOA intermediate (2024)
- CC bulk register is the only discovery surface (API v2 is detail-only)
- 360G GrantNav has no per-org search — cache warming required

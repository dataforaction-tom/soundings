# Runbook — Phase 3 browser smoke

Manual click-through that gates the `v0.4.0-phase-3` tag. Runs against a
freshly-seeded local stack (`make up && make migrate && make seed-light`).

The two new surface areas — trend sparklines on `/place/[id]` and the
`/compare` page — call back to `/v1/tools/get_trend` and
`/v1/tools/compare_places` via SSR, so the smoke validates the whole
front-to-back chain. Anything broken should show up immediately.

## Preconditions

- Docker Compose stack up: `make up`
- Migrations applied: `make migrate`
- Light seed loaded: `make seed-light` (populates ~6 LTLAs + base
  indicators)
- UI dev server running: `cd ui && npm run dev`
- API available at `http://localhost:8001` (or your local override)

## Smoke 1 — sparklines on `/place/[id]`

1. Open <http://localhost:4321/place/ltla24:E06000004>.
2. Expect the Stockton-on-Tees profile to render with grouped indicator
   cards (population, deprivation domains).
3. For each card whose indicator carries a time series (Fingertips life
   expectancy is the most reliable seeded one in `seed-light`), expect a
   small SVG sparkline below the value. The trend should:
   - Have at least 2 points (cards with 0 or 1 trend points skip the
     chart by design).
   - Track the headline value (the rightmost point matches the printed
     "value · unit" string).
4. Loader-mode indicators (e.g. `population.total`) won't have a
   sparkline until Phase 4's `data.trend_point` loaders land — this is
   expected, not a regression.
5. Confirm the "Data behind this answer" panel still shows the raw
   `get_place_profile` payload.

If sparklines fail to render but the cards do: open the network tab and
check `POST /v1/tools/get_trend` calls. A 500 means the orchestrator
errored; check `docker compose logs server`.

## Smoke 2 — `/compare` page

1. Open
   <http://localhost:4321/compare?places=ltla24:E06000004,ltla24:E08000001&indicators=population.total,deprivation.imd.score>.
2. Expect one bar chart per indicator (so two charts on this URL).
   Each chart:
   - Shows the two places on the X axis.
   - Has a percentile label (e.g. `p87`, `p23`) hovering above each bar.
   - Cites the source under the title (`ONS Mid-Year Estimates` for
     population, `MHCLG IMD 2025` for deprivation).
3. Change the `basis` select to "rank" and resubmit — the percentile
   labels should disappear (rank-only basis).
4. Change to "absolute" — rank and percentile both gone, raw values
   only.

If a chart says "No values returned for the selected places": the
adapter didn't yield values for those (place_type, indicator) pairs.
Check the source `available_at` on the indicator vs the place's type.

## Smoke 3 — `/about` mentions the new tools

1. Open <http://localhost:4321/about>.
2. Search the page for "Compare and trend" — the section should describe
   both new surfaces and link to `/compare`.

## Pass / fail criteria

All three smokes must show green before tagging `v0.4.0-phase-3`. Any
red:

- Capture the failing page in a screenshot.
- Note the failing tool call (network tab → request payload + response).
- Fix forward — don't tag a release with broken charts.

## Tag command (after smoke passes)

```bash
git tag -a v0.4.0-phase-3 -m "phase 3: 5 new adapters, compare + trend, charts"
git push origin v0.4.0-phase-3
```

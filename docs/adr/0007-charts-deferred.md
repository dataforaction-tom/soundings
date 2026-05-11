# ADR-0007: Observable Plot charts deferred to Phase 3

**Status:** Accepted
**Date:** 2026-05-11
**Context:** Phase 2 — Block H.

## Decision

`/place/[id]` in Phase 2 renders **single-value indicator cards only**
(IndicatorCard, DomainSection). No charts.

Observable Plot integration (line / bar charts with server-rendered
SVG) and the `IndicatorChart.astro` component arrive in **Phase 3**
alongside the `get_trend` tool, which is when we'll actually have
time-series data worth plotting.

## Why now

A chart of a single value is just a number with extra DOM. Building
the chart pipeline now means writing a component, adding a new
dependency (`@observablehq/plot`), maintaining it across Astro 5
upgrades, and writing tests — all for code that's unused until Phase
3 ships `get_trend`. Pure busywork against current value.

## What lands in Phase 3

- Add `@observablehq/plot` to `ui/package.json`.
- `IndicatorChart.astro` renders Plot's `outerHTML` server-side.
- `/place/[id]` calls `get_trend` per indicator (or fetches a batch)
  and feeds time-series into IndicatorChart inside each card.
- Possibly a tiny "current value" sparkline on cards even before Phase
  3, if a use case shows up.

The Phase 2 plan flagged this deferral explicitly in its "Deferred from
Phase 2" table, so this ADR is the on-disk evidence rather than a new
decision.

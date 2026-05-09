# Soundings

> *Taking the measure of local need.*

An open insight commons for understanding what's happening in places across the UK. A single MCP server wraps UK open data behind question-shaped tools, and every consented question becomes part of a public corpus.

See [`docs/`](./docs/) for the full v1–v3 specs and design docs.

## Status

Phase 0 of v1 — repo and geography spine. See [`docs/plans/2026-05-05-soundings-v1-design.md`](./docs/plans/2026-05-05-soundings-v1-design.md) for the implementation design and [`docs/plans/2026-05-05-soundings-v1-phase-0-plan.md`](./docs/plans/2026-05-05-soundings-v1-phase-0-plan.md) for the current build plan.

## Quick start (dev)

```bash
make decrypt-env       # generate .env from soundings-ops (private)
docker compose up -d
make migrate
make seed-light        # ~5 min, single LTLA worth of data
```

## Licensing

See [LICENSE.md](./LICENSE.md). Server code is AGPL-3.0; schema is CC0; specs are CC BY 4.0.

## Maintained by

[The Good Ship](https://good-ship.co.uk).

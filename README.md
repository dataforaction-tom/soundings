# Soundings

> *Taking the measure of local need.*

An open insight commons for understanding what's happening in places across the UK. A single MCP server wraps UK open data behind question-shaped tools, and every consented question becomes part of a public corpus.

See [`docs/`](./docs/) for the full v1–v3 specs and design docs.

## Status

**Phase 5 of v1** — First monthly corpus release + documentation pass underway.

Phase 0–4 complete: geography spine, population/education/health/crime/civil society indicators, `compare_places` + `get_trend` + `find_organisations_in_place` tools, MCP + HTTP transports, UI with sparklines.

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

# Runbook — Phase 4 browser smoke

Manual click-through that gates the `v0.5.0-phase-4` tag. Runs against a
freshly-seeded local stack with the CC bulk register loaded and a warm
360G cache.

The new surface area — the **Organisations** section on `/place/[id]`
and the `find_organisations_in_place` tool exposed via HTTP and MCP —
exercises the mixed-mode dispatch (CC loader for England/Wales; FTC
passthrough for Scotland/NI) and the 360G per-org grant enrichment.

## Preconditions

- Docker Compose stack up: `make up`
- Migrations applied: `make migrate`
- Light geography seed: `make seed-light` (populates 9k+ places across
  light layers; ~5 min)
- CC bulk register loaded (writes ~170k orgs to `data.organisation` and
  the resolved postcode→LTLA links to `data.organisation_operates_in`):
  ```bash
  docker compose -f infra/docker-compose.yml --project-directory . exec server \
      python -m soundings.loader.run --once charity_commission
  ```
  Takes ~2 min on a Mac mini. Verify with:
  ```sql
  SELECT (SELECT COUNT(*) FROM data.organisation) AS orgs,
         (SELECT COUNT(*) FROM data.organisation_operates_in) AS operates_in;
  ```
- 360G warm cache for the LTLAs you plan to click through:
  ```bash
  docker compose -f infra/docker-compose.yml --project-directory . exec pre_warmer \
      python -m soundings.pre_warmer.run --once threesixtygiving
  ```
  Or, for a single LTLA without spinning up `pre_warmer`:
  ```python
  # python -m soundings.adapters.threesixtygiving.warm_one ltla24:E06000004
  ```
  (Cold cache is fine — first user request will warm it, just slower.)
- UI dev server running: `cd ui && npm run dev`
- API available at `http://localhost:8001` (or your local override)

## Smoke 1 — Organisations section on `/place/[id]` (England)

1. Open <http://localhost:4321/place/ltla24:E06000004>.
2. Scroll past the indicator cards + sparklines to the new
   **Organisations** section. Expect:
   - Section heading `Organisations` followed by an intro line of the
     form *"10 organisations found in this area from Charity Commission
     data."*
   - A responsive grid of organisation cards. Each card shows the
     charity name, a charity_commission source tag, and 0–3 classification
     tags.
   - Where 360G knows about the charity, a `Recent grants` block lists
     up to three grants (funder · amount · date).
   - Citations panel at the bottom includes `charity_commission` and —
     if any grants rendered — `threesixtygiving`.
3. Open the network tab and confirm there's exactly one
   `POST /v1/tools/find_organisations_in_place` for the page, returning
   200 with a JSON envelope of `{ organisations, sources, caveats,
   partial }`.

If the section is missing entirely: check `data.organisation` has rows
linked to this LTLA (`registered_address_place_id =
'ltla24:E06000004'`). If grants are missing on every card: check the
360G cache and rate limits — pre-warming amortises this.

## Smoke 2 — FTC passthrough (Scotland / Northern Ireland)

1. Open <http://localhost:4321/place/ltla24:S12000033> (Aberdeen City).
2. The section should currently render empty / hidden — the UI gates the
   call on `placeId.startsWith("ltla24:E"|"ltla24:W")` while the FTC
   live integration is still rate-limit-conservative. The HTTP tool
   itself should still respond when called directly:
   ```bash
   curl -sS -X POST http://localhost:8001/v1/tools/find_organisations_in_place \
     -H 'Content-Type: application/json' \
     -d '{"place_id":"ltla24:S12000033","limit":5}' | jq .
   ```
   Expect 200 with at least one organisation whose
   `source.source_id == "find_that_charity"` and `cache_status == "live"`.
3. Confirm no `FTC lookup failed:` caveat in the response. (If you see
   one, capture the message and the SC/NI place_id — it usually means
   the FTC endpoint rate-limited us.)

## Smoke 3 — MCP transport parity

1. Connect Claude Desktop (or any MCP-capable client) to the local
   server.
2. Use `find_organisations_in_place` with `place_id =
   "ltla24:E06000004"`.
3. The response payload should be byte-equivalent to the HTTP smoke
   above. The MCP layer is registration boilerplate — anything that
   diverges is a real bug.

## Smoke 4 — `/about` page mentions civil society

1. Open <http://localhost:4321/about>.
2. Expect a `Civil society` heading between **Compare and trend** and
   **Links**, with two sentences explaining the section + the three
   upstream sources (CC, FTC, 360Giving).

## What to do if any smoke fails

- File a regression issue with the failing URL, the network response
  body, and the diff between expected vs observed shape.
- Do **not** tag `v0.5.0-phase-4` until the smoke is fully green.
- Server logs are the most useful next thing to grab:
  `docker compose logs server | tail -200`.

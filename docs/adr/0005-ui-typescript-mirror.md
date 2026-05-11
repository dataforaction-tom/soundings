# ADR-0005: UI TypeScript types mirrored by hand for v1

**Status:** Accepted
**Date:** 2026-05-11
**Context:** Phase 2 — UI scaffold (Task 32).

## Decision

`ui/src/lib/types.ts` mirrors the Pydantic shapes from
`server/soundings/contracts/*` and the tool / capture endpoint
response models **by hand**. When you change a model server-side,
update the TS file in the **same commit**.

## Why not codegen

OpenAPI → TypeScript is the natural alternative. We picked manual sync
for v1 because:

- The tool surface is small (~6 tools + 2 capture endpoints). The
  whole TypeScript file is ~80 lines.
- The Python side moves slowly post-Phase 1 — the contracts are
  pinned by spec §4 and §7.
- A codegen pipeline introduces a build-time dependency on a running
  server (or a checked-in `openapi.json`), both of which add CI
  friction.
- We're a one-person team. The manual cost is paid in seconds; the
  setup cost of codegen is paid in hours.

## When this gets reversed

Switch to auto-generation from the FastAPI OpenAPI schema when **any
one of**:

1. The tool surface gets a seventh tool. (Phase 3 ships `compare_places`
   + `get_trend`, which is +2 — that's the trigger.)
2. We accidentally break the contract — a server-side rename slips
   past code review without an accompanying TS update.
3. We add a second TypeScript consumer (e.g. a mobile client).

The replacement plan: commit a `make openapi` target that writes
`ui/src/lib/types.generated.ts` from `/openapi.json`, drop the manual
file into git history, and add a CI check that fails if the generated
file is stale.

## Until then

The manual file lives next to the API client and is import-only — no
runtime mismatch, just a slow drift risk if the human forgets to
update it. The first violation triggers ADR-0005-superseded.

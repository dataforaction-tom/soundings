# ADR-0004: Corpus publication scope in v1 (local artefacts only)

**Status:** Accepted
**Date:** 2026-05-11
**Context:** Phase 2 — Block E publication tasks
(`docs/plans/2026-05-11-soundings-v1-phase-2-plan.md`).

## Decision

The v1 monthly publication job (`make publish-corpus`) writes **local
artefacts only** to `./corpus/`:

- `corpus-YYYY-MM.csv.gz` (flattened-wide)
- `corpus-YYYY-MM.jsonl.gz` (full nested)
- `manifest.json` (SHA-256s + catalogue_version + sanitisation_rules_version + git sha)

It also creates a local git tag `corpus-YYYY-MM` for reproducibility.
**Pushing the tag and uploading the archives is left to the operator.**

The design (§5) describes pushing to a Backblaze B2 bucket; we
explicitly defer that to a follow-up task gated on:

1. The B2 bucket being created.
2. `B2_KEY_ID` / `B2_APPLICATION_KEY` stored in `soundings-ops`.
3. A decision on whether `/about` reads the bucket index directly
   (single source of truth) or ships a baked list at build time
   (cheap, eventually-consistent).

This ADR exists so future-readers don't think the B2 push was
forgotten — it's a deliberate "local-first" deferral following the
global rule of preferring local artefacts before reaching for a hosted
service.

## Operator workflow in v1

1. `make publish-corpus PERIOD=2026-05`
2. Inspect `./corpus/` — verify row counts, manifest hashes.
3. Decide if the snapshot is releasable.
4. Manually upload to wherever the public download lives (initially
   GitHub releases on the repo).
5. `git push origin corpus-2026-05` to make the tag public.

## When this ADR is superseded

Add a Task 28b in the Phase 2 plan that wires B2 push using the
existing manifest. The local artefact write stays — B2 becomes an
additional sink, not a replacement. ADR-0004 then gets a "superseded
by …" note rather than being deleted, so the deferral history is
visible.

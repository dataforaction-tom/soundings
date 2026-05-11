# ADR-0003: Two-step capture write ordering

**Status:** Accepted
**Date:** 2026-05-11
**Context:** Phase 2 — capture pipeline
(`docs/plans/2026-05-11-soundings-v1-phase-2-plan.md` Block A + Block C).

## Decision

Every tool call writes **two rows in one transaction**:

1. A **stub `corpus.question_record`** — just identity, session, consent
   metadata, tool name, and `result_status`. Lands first because the
   schema FK runs `raw_record.id → question_record.id`.
2. A **full `corpus.raw_record`** — unredacted `tool_inputs`,
   `natural_language_question`, `asker_sector`, `asker_purpose`,
   `geography_referenced`. Same UUID as the stub.

A background task (Task 17) then schedules
`SanitiserWorker.sanitise(record_id)`. The worker reads the raw_record,
runs the sanitisation pipeline, and **updates the same question_record
row in place** with the sanitised fields plus the new `review_status`
and `sanitisation_rules_version`.

## Why a stub instead of "raw first" literally

The Phase 0 schema (migration 0004) created `raw_record.id` as a
foreign key to `question_record.id`. The implementation design said
"raw first, sanitised question_record produced out-of-band," but a
literal reading of that against the existing schema would require
either:

- Reversing the FK direction (a destructive migration that breaks the
  reads-only-raw-once invariant we wanted out of the FK direction in
  the first place), or
- Deferring the FK constraint and accepting a temporary integrity gap.

Instead we land both rows in the **same transaction**: the stub gives
the FK a target, the raw_record carries the unredacted payload, and
no observer ever sees one without the other. Observationally
identical to "raw first" — the only difference is which INSERT runs
microseconds earlier.

The stub also gives the middleware (and `/healthz`, Task 42) something
to count immediately: "this many tool calls captured" doesn't need to
wait for sanitisation.

## Known edge case: permanent-orphan stubs

If the sanitiser worker raises AND the raw_record is later deleted by
the 30-day retention cron (Task 22), the stub question_record stays
forever with `review_status='pending'` and no raw payload to replay
against. These rows:

- Are **never** published (the publication query, Task 24, filters to
  `review_status='cleared'`).
- Don't break any downstream — they're a slow leak of pending stubs
  visible via `/healthz`.
- Could be hard-deleted by a follow-up cron that targets pending stubs
  older than 60 days. Tracked as a Phase 3 follow-up in PLAN.md.

The startup replay (Task 19) catches every stub whose raw_record is
still alive, so the orphan window is bounded by 30 days plus however
long the sanitiser keeps failing.

## Tests that lock the behaviour

- `tests/test_raw_writer.py` — same-transaction write.
- `tests/test_sanitiser_worker.py::test_worker_failure_leaves_record_pending_and_fires_alert` — failure leaves the stub at pending.
- `tests/test_capture_middleware.py::test_background_tasks_set_is_populated_then_drained` — sanitiser task scheduling + drain.

## Future migrations that could change this

If we ever need to make `question_record` independent of `raw_record`
(e.g. so sanitisation runs entirely in-process and we never store raw
data), we'd drop migration 0004's FK in a future migration and rewrite
the writer to skip the raw_record entirely. The capture contract would
be unchanged from the outside — `corpus.question_record` is the
publishable artefact in all cases.

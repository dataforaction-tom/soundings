# ADR-0006: Alerting via Resend (v1)

**Status:** Accepted
**Date:** 2026-05-11
**Context:** Phase 2 — Task 22.

## Decision

The v1 alert mechanism is **email-on-failure via Resend** (design §6).
Failure paths that fire an alert:

1. **Sanitiser exception** (`SanitiserWorker.sanitise`, Task 16) — a
   raw record stays at `review_status='pending'`; ops gets a heads-up
   so they can replay or investigate.
2. **Retention cron failure** (`delete_old_raw_records`, Task 22) —
   raw_record rows aren't being aged out; manual intervention needed
   before the table grows unbounded.
3. **Publication failure** (`make publish-corpus`, Task 27, on the way) —
   monthly corpus didn't materialise.
4. **Loader retry exhaustion** (Phase 1 retry policy, retroactive
   hook to be wired) — an upstream is wedged.

## Implementation

We POST directly to `https://api.resend.com/emails` from `httpx` —
the SDK is unnecessary for the one endpoint we touch and keeps the
dep tree light. `send_alert(subject, body, *, source)` is the public
function; it's **best-effort and never raises** — alert failures must
not cascade into the calling operation.

Environment variables:
- `RESEND_API_KEY` — Bearer token for the Resend API.
- `SOUNDINGS_ALERT_EMAIL` — destination address.

If either is missing, `send_alert` logs a warning and returns. This is
the development default; production sets both in the env.

## Not in v1

- No Prometheus, Loki, PagerDuty, or oncall rotation — explicit
  design §6 deferral.
- No alert deduplication or rate limiting. If the sanitiser fails 100
  times in an hour, ops gets 100 emails. Acceptable for v1 (low
  expected failure rate); revisit if any failure path actually fires
  at meaningful volume.
- No HTML email — plaintext only.

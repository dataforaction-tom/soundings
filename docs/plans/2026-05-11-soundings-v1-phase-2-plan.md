# Soundings v1 — Phase 2 Implementation Plan

> **For Claude:** Same TDD-per-task / commit-per-task discipline as
> Phases 0 and 1 (`docs/plans/2026-05-10-soundings-v1-phase-1-plan.md`).
> Conventions, commit prefixes, and "exact file paths" rules carry over.

**Goal:** Capture every tool call to the corpus, sanitise it for public
release, ship a thin UI over the Phase 1 tools. Phase 2 ends when:

1. Every `POST /v1/tools/*` (and MCP equivalent) writes a `raw_record`
   synchronously inside the tool's response transaction.
2. A background sanitiser produces a publishable `question_record` for
   each raw record, honouring the session's `consent_level`.
3. `make publish-corpus` produces `corpus-YYYY-MM.csv.gz` + `.jsonl.gz` +
   SHA-256 manifest from the current corpus snapshot and tags the git
   commit `corpus-YYYY-MM`.
4. The UI serves `/`, `/place/{id}`, and `/about` against the same tool
   surface external clients use. Everything renders server-side via
   SSR (no `getStaticPaths` pre-render in v1 — Phase 6 polish).
5. A user can submit a question, see the answer with `SourceRef`
   citations, toggle their consent level + asker sector, and those
   choices persist for the session.

**Architecture:** Per `docs/plans/2026-05-05-soundings-v1-design.md` §5
(capture pipeline, two-step write, sanitisation pipeline, monthly
publication) and §6 (Compose stack, Caddyfile, UI service). The corpus
schema (`corpus.question_record`, `corpus.raw_record`) already exists
from Phase 0 migration `0004_cache_and_corpus_schemas.py`; Phase 2 builds
the writer + sanitiser + publication layers on top, plus one additive
migration for `review_status` + `sanitisation_rules_version`.

**Tech stack additions on top of Phase 1:**

| Dep | Purpose | Asked? |
|---|---|---|
| `spacy >= 3.7` + `en_core_web_sm` model | NER for personal-name redaction | Yes — pinned in design §5 |
| `astro@^4` + `@astrojs/node` adapter | UI runtime | Yes — pinned in design §1 |
| `@observablehq/plot` | Server-rendered SVG charts | Deferred to Phase 3 with `get_trend` |
| `vitest` + `@astrojs/test` | UI tests | New; needed for any UI test |
| `resend` (Python SDK) | Email-on-failure alerts | Yes — pinned in design §6 |
| `tar`, `gzip` (stdlib) | CSV/JSONL publication archives | n/a — stdlib |

No Backblaze B2 client in v1 of this plan; publication writes local
artefacts only. Adding B2 push is a follow-up task gated on confirming
the bucket + keys (per global "ask before hosted service" rule).

**Estimated scope:** ~45 tasks across 9 blocks. ~2 focused weeks per
spec §13 — Phase 2's two deliverables (capture + UI) are independent, so
they can be parallelised if needed.

**Prerequisites Tom needs to do once before starting:**

- Decide whether the published corpus pushes to a hosted bucket or stays
  local for v1. Plan defaults to local; if you want B2, add the
  `B2_KEY_ID` / `B2_APPLICATION_KEY` to `soundings-ops` and we'll add
  Task 28b.
- Provision a Resend API key (`RESEND_API_KEY` in `soundings-ops`) and
  decide the destination alert address (`SOUNDINGS_ALERT_EMAIL`).
- Confirm the `en_core_web_sm` model is acceptable; the `_trf` upgrade
  is heavier (~500MB) but more accurate. v1 default = `_sm`.
- Decide whether the consent banner should default to **minimal** (per
  spec/design) or **full** (per spec §12.2 open question). Plan ships
  with `minimal` default and an open question to flip later.

---

## Conventions used in this plan

- **TDD throughout.** Every behaviour task: failing test → minimum
  implementation → green → commit. Pure scaffolding skips the test step
  but still commits.
- **Commits per task** with conventional-commits prefixes (`feat`,
  `chore`, `test`, `refactor`, `docs`, `ci`).
- **Exact file paths.** All paths relative to repo root unless prefixed `/`.
- **No new live-API tests in Phase 2** — capture and UI are local
  concerns; nothing new hits real upstreams.
- **Capture tests use `httpx.AsyncClient(transport=ASGITransport(app))`**
  for HTTP-level assertions; sanitiser tests are synchronous over the DB.
- **UI tests use Vitest** (configured in Task 29) plus optionally
  Playwright for one happy-path e2e in the Phase 2 e2e block. Playwright
  is best-effort: if setup is brittle, the e2e moves to Phase 3.

---

## Block A — Capture contracts + middleware scaffold (Tasks 1–6)

The middleware sits on the FastAPI app and runs for every `/v1/tools/*`
request. It builds a `CaptureContext` per request and hands it to a
synchronous writer at the response boundary.

### Task 1: `CaptureContext` Pydantic model + `nl_question` request field

**Files:**
- Create: `server/soundings/capture/__init__.py`
- Create: `server/soundings/capture/context.py`
- Create: `server/tests/test_capture_context.py`

```python
class CaptureContext(BaseModel):
    session_id: UUID | None    # None for sessions without consent cookies
    consent_level: Literal["full", "minimal", "none"]
    consent_version: str             # e.g. "v1.0"
    tool_called: str
    tool_inputs: dict[str, Any]      # pre-sanitisation
    natural_language_question: str | None  # only populated on full consent
    asker_sector: Literal[
        "charity", "funder", "researcher",
        "commissioner", "public", "other"
    ] | None
    asker_purpose: str | None
```

Each tool's HTTP/MCP request body accepts an optional top-level
`nl_question` field that is NOT a tool argument; the middleware extracts
it before dispatch. External clients can supply it too — preserves the
"UI can't do anything an external client can't" invariant from
design §4.

Test: round-trip through `model_dump_json()` / `model_validate_json()`;
assert UUID, Literal, and Optional fields survive.

Commit: `feat(capture): CaptureContext pydantic model with nl_question`.

### Task 2: `CONSENT_VERSION` constant + consent-banner copy

**Files:**
- Create: `server/soundings/capture/consent.py`
- Create: `server/tests/test_consent_version.py`

```python
CONSENT_VERSION = "v1.0"  # bumped whenever banner copy changes
CONSENT_LEVELS: tuple[str, ...] = ("full", "minimal", "none")
DEFAULT_CONSENT_LEVEL = "minimal"
ASKER_SECTORS: tuple[str, ...] = (
    "charity", "funder", "researcher",
    "commissioner", "public", "other",
)
CONSENT_BANNER_COPY = {"v1.0": "..."}  # short, plain-English text
```

Test: assert `CONSENT_BANNER_COPY[CONSENT_VERSION]` exists and is
non-empty.

Commit: `feat(capture): consent version + banner copy + sector vocab`.

### Task 3: Session/consent cookie middleware

**Files:**
- Create: `server/soundings/http/session.py`
- Create: `server/tests/test_session_cookie.py`

Middleware that reads three cookies (`soundings_session`,
`soundings_consent`, `soundings_sector`) on every request, validates
them against the controlled vocabularies, and attaches a
`CaptureContext` (without tool fields yet) to `request.state`. If
cookies are missing, the session UUID is **not** set and **no
`Set-Cookie` header is emitted** — cookies only get written when the
client explicitly accepts consent (via the UI consent-banner POST in
Task 4).

Also flips `CORSMiddleware.allow_credentials` to `True` on the existing
config so cookies round-trip on cross-origin requests. Origins stay
locked to `SOUNDINGS_UI_ORIGIN`.

Tests:
1. Request with no cookies → `request.state.session_id is None`, no
   `Set-Cookie` header.
2. Request with valid `soundings_session` + `soundings_consent=minimal`
   → `CaptureContext` populated.
3. Request with malformed UUID → cookie silently ignored, no error.
4. Request with invalid `soundings_sector` value → sector cleared to
   `None`, no error.

Commit: `feat(http): session/consent/sector cookie middleware + CORS credentials`.

### Task 4: `POST /v1/capture/consent` — record consent + issue cookies

**Files:**
- Create: `server/soundings/http/capture.py`
- Modify: `server/soundings/app.py` (router include)
- Create: `server/tests/test_capture_consent.py`

```yaml
input:
  consent_level: "full" | "minimal" | "none"
  asker_sector: string | optional   # one of ASKER_SECTORS or null
output:
  session_id: uuid
  consent_level: same
  asker_sector: same
  consent_version: "v1.0"
side-effects:
  Set-Cookie: soundings_session=<uuid>; SameSite=Lax; HttpOnly
  Set-Cookie: soundings_consent=<level>; SameSite=Lax
  Set-Cookie: soundings_sector=<sector|""; SameSite=Lax (omitted if null)
```

Tests:
1. POST `consent_level=minimal` → 200, body has new UUID + level,
   Set-Cookie headers present.
2. POST `consent_level=full, asker_sector=charity` → cookie issued with
   sector.
3. Subsequent request to `/v1/tools/find_place` with these cookies
   carries the context forward (`asker_sector` reaches CaptureContext).
4. POST `consent_level=none` → cookies set; **no records are written**
   downstream.

Commit: `feat(http): POST /v1/capture/consent with asker_sector`.

### Task 5: `CaptureMiddleware` skeleton + `nl_question` extraction

**Files:**
- Create: `server/soundings/capture/middleware.py`
- Modify: `server/soundings/app.py`
- Create: `server/tests/test_capture_middleware.py`

ASGI middleware that wraps every `/v1/tools/*` POST. Pre-call:

1. Reads `CaptureContext` (session+consent+sector) from `request.state`.
2. Pops the top-level `nl_question` field from the JSON body before it
   reaches the tool handler. If `consent_level != "full"`, discards
   `nl_question` immediately (never written anywhere).
3. Stashes the (possibly discarded) `nl_question` on `request.state` so
   the post-handler can include it in the raw payload.

Post-call: reads the tool response, extracts `tool_called`,
`result_status`, `error_class`, `indicators_returned`, `sources_used`,
`geography_referenced`, hands the full `CaptureContext` to the
`RawRecordWriter` (Task 6).

Test (mock writer): POST `/v1/tools/find_place` with cookies + a
top-level `nl_question`, assert writer was called with
`tool_called="find_place"`, `indicators_returned == []`,
`natural_language_question` matches the input.

Commit: `feat(capture): middleware extracts CaptureContext + nl_question per tool call`.

### Task 6: `RawRecordWriter` — synchronous stub + raw write

**Files:**
- Create: `server/soundings/capture/raw_writer.py`
- Create: `server/tests/test_raw_writer.py`

Writes a stub row into `corpus.question_record` (just `id`, `timestamp`,
`session_id`, `consent_version`, `capture_level`, `tool_called`,
`result_status`) and a full `corpus.raw_record` row with the unredacted
payload. Both in the same transaction as the tool's response. The FK
`raw_record.id → question_record.id` is satisfied by writing the stub
first.

**Note:** the design says "raw first" but the schema FK forces a stub
question_record first; the practical behaviour is identical (both rows
land in one txn). ADR-0003 (Task 18) documents this plus the
permanent-orphan stub edge case.

If `capture_level == "none"`: no rows written.

Test (integration): POST `find_place`, assert `corpus.raw_record` has 1
row and `corpus.question_record` has the stub. POST again with
`capture_level=none` cookie: row count unchanged.

Commit: `feat(capture): RawRecordWriter writes stub question + raw payload`.

---

## Block B — Sanitisation pipeline (Tasks 7–14)

Pure functions over a `RawRecord` payload, composed into a pipeline.
Each rule reports which fields it touched and how many times it fired,
so the multi-fire / flag-for-review logic can act on aggregate
signals.

### Task 7: `catalogue/sanitisation.yaml` + loader

**Files:**
- Create: `catalogue/sanitisation.yaml`
- Create: `server/soundings/capture/sanitisation/__init__.py`
- Create: `server/soundings/capture/sanitisation/config.py`
- Create: `server/tests/test_sanitisation_config.py`

```yaml
# catalogue/sanitisation.yaml
version: "v1"
small_org:
  income_threshold_gbp: 100000  # design §5
asker_purpose:
  max_chars: 280
  rate_limit:
    full_consent_per_session_per_hour: 60
geography:
  redact_finer_than: "msoa21"   # in free-text fields
```

Test: load + parse, assert version `v1`, assert all rule thresholds
present.

Commit: `feat(catalogue): sanitisation.yaml + loader`.

### Task 8: `SanitisationRule` protocol + `SanitisationResult`

**Files:**
- Create: `server/soundings/capture/sanitisation/protocol.py`
- Create: `server/tests/test_sanitisation_protocol.py`

```python
@dataclass
class SanitisationResult:
    payload: dict[str, Any]
    fields_changed: set[str]
    fires: int    # times this rule fired on this record

class SanitisationRule(Protocol):
    name: str
    def apply(self, payload: dict[str, Any], config: SanitisationConfig)
        -> SanitisationResult: ...
```

Test: a fake rule that always fires returns `fires=1` and includes the
target field in `fields_changed`.

Commit: `feat(capture): SanitisationRule protocol + result`.

### Task 9: `StripDirectIdentifiers` rule (postcodes + emails + phones)

**Files:**
- Create: `server/soundings/capture/sanitisation/direct_identifiers.py`
- Create: `server/tests/test_strip_direct_identifiers.py`

Reads any string field in the payload (recursive), strips three classes
of direct identifier:

- **Unit postcodes**: `[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}` → preserve
  sector or higher (`TS18 1AB` → `TS18 1`).
- **Email addresses**: `[\w.+-]+@[\w-]+\.[a-z]{2,}` → `[redacted email]`.
- **UK phone numbers**: `0[\d\s]{8,12}` matching common UK landline /
  mobile patterns → `[redacted phone]`. Conservative: false negatives
  acceptable, false positives on long bare numbers acceptable too.

One fire per match (across all three classes).

Tests:
1. `"reach me at tom@example.org or TS18 1AB"` → both redacted, `fires=2`.
2. `"call 07700 900123"` → `"[redacted phone]"`, `fires=1`.
3. Sector-only `"TS18 area"` → unchanged.

Commit: `feat(sanitisation): strip postcodes, emails, phone numbers`.

### Task 10: `StripFineGeographyInFreeText` rule

**Files:**
- Create: `server/soundings/capture/sanitisation/fine_geography.py`
- Create: `server/tests/test_strip_fine_geography.py`

In free-text fields (`natural_language_question`, `asker_purpose`),
matches LSOA codes (`E0\d{7}`) and any `geography.place.name` for LSOA
or MSOA, replaces with `[redacted area]`. Place names looked up from
`geography.place` for `type IN ('lsoa21','msoa21')`.

Tests:
1. `"E01012018 is interesting"` → `"[redacted area] is interesting"`,
   `fires=1`.
2. `"Stockton 010A"` (an LSOA place name) → redacted.
3. `"Stockton-on-Tees"` (LTLA name) → preserved.

Commit: `feat(sanitisation): redact LSOA/MSOA references in free text`.

### Task 11: `StripPersonalNamesViaNER` rule

**Files:**
- Create: `server/soundings/capture/sanitisation/personal_names.py`
- Create: `server/tests/test_strip_personal_names.py`

Uses `spacy` with `en_core_web_sm`. Loads the model once at import time
(cached); per-record runs the model over free-text fields, redacts spans
labelled `PERSON`. Adds the dependency to `pyproject.toml` and pins the
spaCy model URL in `server/scripts/install_spacy_model.py` (called from
`Makefile install` target).

Tests:
1. `"Tom asked about Stockton"` → `"[redacted name] asked about
   Stockton"`, `fires=1` (provided the local model recognises "Tom"
   — accept any single-token redaction).
2. `"the council asked about Stockton"` → unchanged, `fires=0`.

If spaCy isn't installed in the test env, mark the test
`@pytest.mark.skip("spaCy model not loaded")`. CI must run `make
install-spacy` before pytest.

Commit: `feat(sanitisation): personal-name redaction via spaCy NER`.

### Task 12: `StripSmallOrgNames` rule

**Files:**
- Create: `server/soundings/capture/sanitisation/small_orgs.py`
- Create: `server/tests/test_strip_small_orgs.py`

Reads `data.organisation` (populated in Phase 4 — for Phase 2 we seed
test fixtures only). For any org with `income < income_threshold_gbp`
(from `sanitisation.yaml`), redact mentions of its `name` in free-text
fields.

For Phase 2, the table will be empty in production seeds; the rule is
present, tested with fixtures, and ready for Phase 4 to fill the table.

Tests:
1. Seed two orgs (one £20k, one £500k); fixture text mentions both →
   only the small one is redacted.
2. Empty `organisation` table → rule is a no-op, `fires=0`.

Commit: `feat(sanitisation): redact small-org names by income threshold`.

### Task 13: `NormaliseAskerPurpose` + `ValidateConsentLevel` rules

**Files:**
- Create: `server/soundings/capture/sanitisation/normalise.py`
- Create: `server/tests/test_normalise_rules.py`

`NormaliseAskerPurpose`: collapses whitespace, trims, truncates to
`asker_purpose.max_chars`. Doesn't count as a "fire" unless truncation
actually removed text.

`ValidateConsentLevel`: if `capture_level == "none"`, return an empty
payload (the publication query excludes these anyway, but defensive).

Tests:
1. 300-char `asker_purpose` → truncated to 280, `fires=1`.
2. `"  hello   world  "` → `"hello world"`, `fires=0`.
3. `capture_level="none"` → empty payload.

Commit: `feat(sanitisation): normalise asker_purpose + validate consent`.

### Task 14: Pipeline runner + flag-for-review on multi-fire

**Files:**
- Create: `server/soundings/capture/sanitisation/pipeline.py`
- Create: `server/tests/test_sanitisation_pipeline.py`

```python
PIPELINE: list[SanitisationRule] = [
    StripDirectIdentifiers(),
    StripFineGeographyInFreeText(),
    StripPersonalNamesViaNER(),
    StripSmallOrgNames(),
    NormaliseAskerPurpose(),
    ValidateConsentLevel(),
]

@dataclass
class PipelineOutcome:
    sanitised_payload: dict[str, Any]
    total_fires: int
    rules_fired: list[str]
    review_status: Literal["cleared", "flagged"]   # flagged if total_fires >= 2

def run_pipeline(raw_payload, config) -> PipelineOutcome: ...
```

Tests:
1. Payload that triggers one rule → `review_status="cleared"`.
2. Payload that triggers two rules → `review_status="flagged"`.
3. Pipeline preserves field order and only mutates targeted fields.

Commit: `feat(sanitisation): pipeline runner with multi-fire flagging`.

---

## Block C — Schema migration + question-record writer + out-of-band sanitiser (Tasks 15–19)

### Task 15: Schema migration — `review_status` + `sanitisation_rules_version`

**Files:**
- Create: `server/soundings/db/migrations/versions/0005_question_record_review_status.py`
- Modify: `server/soundings/db/models/corpus.py`
- Create: `server/tests/test_question_record_review.py`

Adds:
- `review_status` `VARCHAR(16)` default `'pending'`. Values: `pending`,
  `cleared`, `flagged`, `released`.
- `sanitisation_rules_version` `VARCHAR(32)` nullable; written by the
  sanitiser.

Migration runs before any sanitiser code in Task 16 so the column
exists when the worker writes to it.

Tests: insert a row with default `review_status`, assert it reads back
as `pending`.

Commit: `feat(db): question_record review_status + sanitisation_rules_version`.

### Task 16: Sanitiser worker — read raw, write sanitised fields onto question_record

**Files:**
- Create: `server/soundings/capture/sanitiser_worker.py`
- Create: `server/tests/test_sanitiser_worker.py`

A coroutine `sanitise_one(record_id, engine)` that:

1. Loads `corpus.raw_record` row by id.
2. Runs the pipeline against `raw_payload`.
3. Updates the matching `corpus.question_record` row with sanitised
   `natural_language_question`, `tool_inputs_redacted`,
   `geography_referenced`, `asker_purpose`, and the
   `review_status` from the pipeline outcome.
4. Writes the active `sanitisation.yaml` `version` into
   `sanitisation_rules_version`.

Failure path: logs the exception and emits a Resend alert via
`soundings.alerts.send_alert` (Task 22). The question_record stays at
`review_status='pending'` and gets picked up by the startup replay
(Task 19).

Tests: write a raw_record + stub question_record, call `sanitise_one`,
assert question_record now has sanitised values and matching
`review_status`. Force exception → record stays `pending`, alert
function is called.

Commit: `feat(capture): sanitiser worker writes sanitised fields onto question_record`.

### Task 17: Middleware fires sanitiser via tracked `asyncio.create_task`

**Files:**
- Modify: `server/soundings/capture/middleware.py`
- Modify: `server/soundings/app.py` (initialise `app.state.background_tasks`)
- Modify: `server/tests/test_capture_middleware.py`

After the raw_record write commits, the middleware schedules the
sanitiser:

```python
task = asyncio.create_task(sanitise_one(record_id, engine))
request.app.state.background_tasks.add(task)
task.add_done_callback(request.app.state.background_tasks.discard)
```

This holds a strong reference so the event loop can't drop the task
under memory pressure. `app.state.background_tasks: set[asyncio.Task]`
is initialised in the lifespan handler.

Tests:
1. POST a tool call, then poll the question_record until its
   `review_status` is `cleared` or timeout — assert it lands within
   2s in tests.
2. Force `sanitise_one` to raise → response still 200, raw_record
   present, question_record stays at `review_status='pending'`,
   `app.state.background_tasks` clears.
3. Assert `background_tasks` is non-empty between scheduling and
   completion (use a slow fake sanitiser).

Commit: `feat(capture): fire sanitiser as tracked background task`.

### Task 18: ADR-0003 — two-step capture write ordering

**Files:**
- Create: `docs/adr/0003-two-step-capture-write.md`

Explains why the schema has `raw_record.id → question_record.id` FK
(it was Phase 0 / migration 0004), while the design says "raw first".
Resolution: a stub question_record row lands in the same txn as the
raw_record, sanitiser updates that same row out-of-band.

Documents the **permanent-orphan stub** edge case: if the sanitiser
fails AND the raw_record is later deleted by the 30-day retention cron
(Task 22), the stub question_record is left with
`review_status='pending'` and no raw payload to replay against. The
publication query (Task 24) excludes `pending`, so these never reach
the corpus, but they accumulate. Phase 3 follow-up: a cron that
hard-deletes pending stubs older than 60 days.

Commit: `docs(adr): 0003 — two-step capture write ordering`.

### Task 19: Replay endpoint + startup re-queue with back-pressure

**Files:**
- Create: `server/soundings/capture/replay.py`
- Modify: `server/soundings/app.py` (lifespan hook)
- Create: `server/tests/test_capture_replay.py`

`replay_pending(engine, *, max_concurrent=4)` selects all
`corpus.question_record` rows where `review_status='pending'` AND
`raw_record` is still present (within 30-day retention). It runs
`sanitise_one` for each through an `asyncio.Semaphore(max_concurrent)`
to cap spaCy parallelism on the Mac mini's ~400MB server budget.

Called once on app startup (so a process crash mid-sanitise self-heals);
also exposed as `python -m soundings.capture.replay --all` for ops.

A CLI flag `--since YYYY-MM-DD` allows replaying after a sanitisation
rule change.

Tests:
1. Seed two `pending` records, call `replay_pending`, both move to
   `cleared`.
2. `--since` only picks up rows newer than the cutoff.
3. Concurrency cap honoured: seed 10 records, force `sanitise_one` to
   sleep, observe at most 4 in flight at once.

Commit: `feat(capture): replay pending records with concurrency cap`.

---

## Block D — Abuse guards + feedback + retention + alerts (Tasks 20–23)

### Task 20: Per-session asker_purpose rate limit

**Files:**
- Create: `server/soundings/capture/rate_limit.py`
- Modify: `server/soundings/capture/middleware.py`
- Create: `server/tests/test_capture_rate_limit.py`

Within the middleware: count this session's full-consent records in
`corpus.question_record` over the last hour. If `>= 60`, force this
record's `capture_level` to `"minimal"` (strip the natural-language
question before raw_record writes). The asker is silently downgraded
— no error.

Tests:
1. Submit 60 full-consent requests in a tight loop → 61st lands as
   `minimal` even though cookie says `full`.
2. After an hour gap, full consent re-engages.

Commit: `feat(capture): downgrade to minimal after per-session full-consent rate limit`.

### Task 21: `POST /v1/capture/feedback` (marked_useful)

**Files:**
- Modify: `server/soundings/http/capture.py`
- Create: `server/tests/test_capture_feedback.py`

```yaml
input:
  question_record_id: uuid
  marked_useful: boolean
output:
  ok: true
```

Authorisation: only the original session can mark its own records. We
check `session_id` on the question_record matches the cookie session.

Tests:
1. POST with valid `question_record_id` from the same session → 200,
   row updated.
2. POST from a different session → 403.

Commit: `feat(http): POST /v1/capture/feedback`.

### Task 22: Alerts via Resend + 30-day raw_record retention cron

**Files:**
- Create: `server/soundings/alerts/__init__.py`
- Create: `server/soundings/alerts/resend.py`
- Create: `server/soundings/capture/retention.py`
- Modify: `server/soundings/loader/run.py` (register retention cron)
- Create: `server/tests/test_alerts.py`
- Create: `server/tests/test_capture_retention.py`
- Create: `docs/adr/0006-alerting-via-resend.md`

`send_alert(subject, body, *, source: str)` posts to Resend, using
`RESEND_API_KEY` and `SOUNDINGS_ALERT_EMAIL` from env. If either env is
missing, the function logs a warning and returns — no hard failure.

A daily APScheduler job deletes `corpus.raw_record` rows older than
30 days. Logs the count deleted. Failure calls `send_alert`. Does NOT
delete question_record rows.

ADR-0006 pins Resend as the v1 alert mechanism (per design §6) and
lists the four failure paths that should alert: sanitiser exception
(Task 16), retention cron failure (this task), publication failure
(Task 28), and loader run failure (Phase 1 retry exhaustion, retroactive
hook).

Tests:
1. Mock httpx; assert `send_alert` posts to Resend with the right body.
2. Missing env vars → logs warning, no exception.
3. Seed a 31-day-old raw_record + a fresh one → only the old one is
   deleted.
4. question_record rows survive the cleanup.

Commit: `feat(capture): alerts via Resend + 30-day raw_record retention`.

### Task 23: ADR-0004 — corpus publication scope (local, no B2 yet)

**Files:**
- Create: `docs/adr/0004-corpus-publication.md`

Documents that v1 of the publication job writes local artefacts only.
Pushing to Backblaze B2 (per design §5) is a follow-up gated on:

1. B2 bucket created + keys in `soundings-ops`.
2. Decision on whether `/about` reads the bucket index directly or
   ships a baked list at build time.

This ADR exists because the design §5 has a B2 push step that we're
deliberately deferring; future-self should know it wasn't a forgotten
requirement.

Commit: `docs(adr): 0004 — corpus publication scoped to local artefacts in v1`.

---

## Block E — Monthly publication job (Tasks 24–28)

### Task 24: Publication snapshot query

**Files:**
- Create: `server/soundings/publication/__init__.py`
- Create: `server/soundings/publication/snapshot.py`
- Create: `server/tests/test_publication_snapshot.py`

`select_publishable(engine, period_end)` returns all `question_record`
rows where:
- `consent_version IS NOT NULL`
- `capture_level IN ('full','minimal')` (never `none`)
- `review_status = 'cleared'` (not `flagged`, not `pending`,
  not `released`)
- `timestamp < period_end` (typically start of current month)

Result is a deterministic ordered iterator (sorted by `timestamp` then
`id`) so two runs over the same DB produce identical output.

Tests:
1. Seed four records: cleared+full, flagged+full, cleared+none,
   pending+minimal → only the first is selected.
2. Two calls with the same `period_end` return identical id sequences.

Commit: `feat(publication): publishable record snapshot query`.

### Task 25: CSV + JSONL writers

**Files:**
- Create: `server/soundings/publication/writers.py`
- Create: `server/tests/test_publication_writers.py`

`write_csv(records, path)` writes a flattened-wide CSV with stable
column order: `id, timestamp, session_id, consent_version,
capture_level, tool_called, geography_types, indicators_returned,
sources_used, result_status, asker_sector, marked_useful`.

`write_jsonl(records, path)` writes one JSON object per line with the
full nested shape (including `tool_inputs_redacted`,
`geography_referenced`, `asker_purpose`).

Both gzip the output (`.csv.gz`, `.jsonl.gz`).

Tests:
1. Three records → 3 lines in both files (after gunzip).
2. CSV column order matches the spec.

Commit: `feat(publication): CSV + JSONL writers (gzipped)`.

### Task 26: SHA-256 manifest with versions

**Files:**
- Create: `server/soundings/publication/manifest.py`
- Create: `server/tests/test_publication_manifest.py`

`write_manifest(output_dir, files, period, catalogue_version,
sanitisation_rules_version)` produces `manifest.json`:

```json
{
  "period": "2026-05",
  "files": [
    {"name": "corpus-2026-05.csv.gz", "sha256": "...", "size_bytes": N},
    {"name": "corpus-2026-05.jsonl.gz", "sha256": "...", "size_bytes": N}
  ],
  "catalogue_version": "<sha256 of indicators.yaml at run time>",
  "sanitisation_rules_version": "v1",
  "generator_git_sha": "<git rev-parse HEAD>"
}
```

Tests:
1. Manifest references both files and matches their bytes' sha256.
2. `catalogue_version` matches the value `load_catalogue_into_db`
   stamps on indicator rows for this run.

Commit: `feat(publication): SHA-256 manifest with version pins`.

### Task 27: `make publish-corpus` CLI + git tag step

**Files:**
- Modify: `Makefile`
- Create: `server/soundings/publication/cli.py`
- Create: `server/tests/test_publication_cli.py`

```
make publish-corpus PERIOD=2026-05 OUT=./corpus-out
```

Default `OUT` is `./corpus/`. Default `PERIOD` is the previous month.
Writes both archives + manifest, prints the manifest sha256s to stdout.

After a successful write, the CLI shells out to `git tag corpus-YYYY-MM
-m "Corpus snapshot YYYY-MM"`. Existing tag → skip with a warning (so
re-runs of the same period don't fail). The push of that tag is left
to the operator (`git push origin corpus-YYYY-MM`) — per global rule,
don't push without confirmation.

Failure path calls `send_alert` (Task 22).

Tests:
1. Run with seeded records → three files materialise in OUT, git tag
   exists locally.
2. Re-run for the same period → archives re-written, tag step warns
   but doesn't fail.
3. Force failure mid-write → `send_alert` called.

Commit: `feat(publication): make publish-corpus CLI with git tag`.

### Task 28: e2e smoke for publication pipeline

**Files:**
- Create: `server/tests/test_publication_e2e.py`

End-to-end:
1. Seed one full-consent, cleared question_record dated 5 days ago.
2. Run `python -m soundings.publication.cli --period 2026-05 --out
   /tmp/corpus-test/`.
3. Assert: three files exist, the CSV has 1 row, the JSONL has 1 line,
   the manifest hashes match. Verify the git tag exists locally.

Commit: `test: phase 2 publication e2e`.

---

## Block F — UI scaffold (Tasks 29–32)

### Task 29: `ui/` Astro 4 init + Vitest config

**Files:**
- Create: `ui/package.json`
- Create: `ui/astro.config.mjs`
- Create: `ui/tsconfig.json`
- Create: `ui/vitest.config.ts`
- Create: `ui/src/env.d.ts`
- Create: `ui/.gitignore`
- Create: `ui/tests/.gitkeep`

Astro 4 with `@astrojs/node` adapter in `standalone` mode (so `node
./dist/server/entry.mjs` boots the production server). TypeScript
strict. Vitest with `jsdom` env for component tests. **All routes
SSR by default** (`output: "server"` in astro.config) — no
`getStaticPaths` pre-rendering in v1; that's a Phase 6 polish task.

`package.json` scripts:
```
"dev": "astro dev",
"build": "astro build",
"start": "node ./dist/server/entry.mjs",
"test": "vitest --run"
```

No test in this task — pure scaffolding. Commit: `chore(ui): Astro 4 + Vitest init`.

### Task 30: `infra/Dockerfile.ui` + Compose service

**Files:**
- Create: `infra/Dockerfile.ui`
- Modify: `infra/docker-compose.yml`

Multi-stage build: `node:20-alpine` for `npm ci && npm run build`,
then `node:20-alpine` for the runtime. **Build is fully offline** —
no API calls at `astro build` time because everything is SSR. Binds
`127.0.0.1:4321`. `depends_on: [server]`. `restart: unless-stopped`.

Commit: `chore(infra): UI Dockerfile + compose service`.

### Task 31: Caddyfile path routing

**Files:**
- Modify: `infra/Caddyfile`

Adds the three handlers per design §6:

```caddy
:80 {
    handle /mcp/* { reverse_proxy server:8000 }
    handle /v1/*  { reverse_proxy server:8000 }
    handle        { reverse_proxy ui:4321 }
}
```

The existing `:80` block needs replacement, not duplication. Test by
`docker compose up` and hitting both `/v1/sources` and `/`.

Commit: `chore(infra): Caddy path routing for /v1, /mcp, ui`.

### Task 32: `ui/src/lib/api.ts` — thin HTTP client to `/v1/tools/*`

**Files:**
- Create: `ui/src/lib/api.ts`
- Create: `ui/src/lib/types.ts`
- Create: `ui/tests/api.test.ts`
- Create: `docs/adr/0005-ui-typescript-mirror.md`

Typed wrappers for `find_place`, `get_indicators`, `get_place_profile`,
and `POST /v1/capture/{consent,feedback}`. Uses native `fetch` with
`credentials: "include"` so cookies round-trip. Default base URL from
`SOUNDINGS_API_BASE` env (defaults to `http://server:8000` inside the
container, `http://localhost:8000` for `npm run dev`).

`types.ts` mirrors the Pydantic shapes from
`server/soundings/contracts/` — kept in sync by hand for now. ADR-0005
documents this and the switch-to-codegen trigger (seventh tool or
contract break).

Vitest test: mock `fetch`, assert URL, method, and `credentials: "include"`.

Commit: `feat(ui): typed API client for /v1 tools + ADR-0005`.

---

## Block G — `/` index page + consent banner (Tasks 33–36)

### Task 33: Shared layout + consent banner (with sector dropdown)

**Files:**
- Create: `ui/src/layouts/Base.astro`
- Create: `ui/src/components/ConsentBanner.astro`
- Create: `ui/src/components/ConsentBanner.tsx` (interactive island)
- Create: `ui/tests/ConsentBanner.test.ts`

The banner renders the current consent level + sector (read from
cookies via `Astro.cookies`). Controls:
- Three radio buttons for `full | minimal | none`.
- A dropdown for `asker_sector` (only enabled when consent is `full` or
  `minimal`).

Submission POSTs to `/v1/capture/consent` with `credentials: include`
and reloads.

Test: render with no cookie, assert `minimal` is default; click
`full`, assert POST to `/v1/capture/consent` with `consent_level=full`;
choose `charity` from sector dropdown, assert it's included in payload.

Commit: `feat(ui): consent banner with sector dropdown`.

### Task 34: `/` index page — search + dispatch

**Files:**
- Create: `ui/src/pages/index.astro`
- Create: `ui/src/components/SearchBox.tsx`
- Create: `ui/tests/index.test.ts`

Single `<input>` "What do you want to know about a place?" + submit.
The input value becomes both the `query` for `find_place` AND the
`nl_question` (passed as a top-level body field) if the session has
`full` consent.

Server-side handler:

1. POSTs the text to `/v1/tools/find_place` (with `nl_question` if
   `consent_level=full`).
2. If exactly one match → redirect to `/place/{matches[0].id}`.
3. If multiple → render disambiguation list.
4. If zero → render "no match found" + suggestion text.

Test: mocked API client returning one match → render redirects;
mocked returning three matches → list with three links.

Commit: `feat(ui): / index page with search + dispatch`.

### Task 35: Result page (when search produces multiple matches)

**Files:**
- Create: `ui/src/pages/search.astro`
- Create: `ui/tests/search.test.ts`

Lists place candidates with type badge, name, and "contained in" parent
hierarchy. Each item links to `/place/{id}`.

Test: 3 candidates → 3 list items with correct hrefs.

Commit: `feat(ui): /search disambiguation page`.

### Task 36: Source citations + "data behind this" panel

**Files:**
- Create: `ui/src/components/SourceCitations.astro`
- Create: `ui/src/components/DataPanel.astro`
- Create: `ui/tests/SourceCitations.test.ts`
- Create: `ui/tests/DataPanel.test.ts`

`SourceCitations` renders the deduplicated `SourceRef[]` returned
alongside every tool response. Shows `source_label`, `publisher`,
`retrieved_at`, `cache_status` badge, link to `dataset_url`.

`DataPanel` renders the raw tool call(s) + response (pretty-printed
JSON) inside a collapsed `<details>`. Used by both `/` and `/place/[id]`
to keep the "UI ≡ external client" invariant visible.

Tests:
1. 3 SourceRefs (2 duplicates) → 2 items rendered.
2. DataPanel given a sample tool response → JSON visible inside
   `<details>`.

Commit: `feat(ui): source citations + data-behind-this panel`.

---

## Block H — `/place/{id}` profile page (Tasks 37–40)

### Task 37: SSR route + profile fetcher

**Files:**
- Create: `ui/src/pages/place/[id].astro`
- Create: `ui/src/lib/profile.ts`
- Create: `ui/tests/profile.test.ts`

SSR-only route (`prerender = false` explicitly). `fetchProfile(placeId)`
calls `POST /v1/tools/get_place_profile` with
`include=["population","deprivation"]` and returns the typed response.
Errors surface as a render-time `<div class="error">` rather than
throwing.

Test: mock API returning a profile with two indicators → page renders
both indicator labels.

Commit: `feat(ui): /place/[id] SSR route with profile fetcher`.

### Task 38: Indicator cards

**Files:**
- Create: `ui/src/components/IndicatorCard.astro`
- Create: `ui/tests/IndicatorCard.test.ts`

One card per indicator: label, value + unit, period, `cache_status`
badge, last-updated dates. Cards are grouped by domain (deprivation,
population, etc.) — domain inferred from the indicator key prefix.

Test: card for `population.total=200000` → renders "200,000 persons"
with the right unit.

Commit: `feat(ui): indicator card component`.

### Task 39: Domain grouping + page layout

**Files:**
- Modify: `ui/src/pages/place/[id].astro`
- Create: `ui/src/components/DomainSection.astro`
- Create: `ui/tests/place_page.test.ts`

Indicator cards group into `DomainSection`s ("Population",
"Deprivation"). Each section has a heading + the relevant cards in a
grid. Page includes the consent banner, source citations, and a
"data behind this" panel.

Test: mock 4 indicators across 2 domains → 2 sections rendered with
correct heading + card count.

Commit: `feat(ui): domain grouping on /place/[id]`.

### Task 40: Note: charts deferred to Phase 3

**Files:**
- Create: `docs/adr/0007-charts-deferred.md`

A one-paragraph ADR explaining why Observable Plot integration was
deferred to Phase 3: Phase 2 only shows single indicator values, not
trends; chart UI without data is busywork. Phase 3's `get_trend` tool
brings time-series, and that's when charts arrive.

Commit: `docs(adr): 0007 — charts deferred to Phase 3 with get_trend`.

---

## Block I — `/about` + Phase 2 integration + tag (Tasks 41–45)

### Task 41: `/about` page

**Files:**
- Create: `ui/src/pages/about.astro`
- Create: `ui/src/content/about.md`
- Create: `ui/tests/about.test.ts`

Markdown content explaining: what Soundings is, how capture works,
links to:

- `/corpus/` (when populated by Block E)
- The public GitHub repo
- `docs/v1-orchestration-and-capture.md` rendered version

Test: page renders, contains the consent banner, contains all three
required links.

Commit: `feat(ui): /about page`.

### Task 42: `/healthz` reflects capture pipeline freshness

**Files:**
- Modify: `server/soundings/http/health.py`
- Modify: `server/tests/test_healthz.py`

Adds a `capture` check that reports:

- Last `raw_record` write timestamp.
- Count of `question_record` rows with `review_status='pending'` older
  than 1 hour (warns if > 100).
- Last successful retention-cron run.

Healthz flips `degraded` if the pending backlog exceeds 1000 or the
retention cron hasn't run in 48 hours.

Test: seed conditions for healthy and degraded; assert healthz reflects
each.

Commit: `feat(http): /healthz includes capture-pipeline freshness`.

### Task 43: Phase 2 e2e test — capture pipeline + publication

**Files:**
- Create: `server/tests/test_phase_2_e2e.py`

End-to-end:

1. `POST /v1/capture/consent` with `consent_level=full,
   asker_sector=charity`, capture cookies.
2. `POST /v1/tools/get_indicators` for a Stockton LTLA with
   `nl_question` carrying a postcode + email.
3. Poll `corpus.question_record` until `review_status='cleared'`.
4. Assert the sanitised question redacted both the postcode (to sector)
   and the email; `asker_sector` survived to the record.
5. Run the publication query → record appears in the output.
6. Run `make publish-corpus PERIOD=2026-05 OUT=/tmp/corpus-test/` →
   manifest + both archives exist + CSV row count = 1.

Commit: `test: phase 2 e2e — capture + sanitisation + publication`.

### Task 44: Phase 2 e2e test — UI happy-path via Playwright (best-effort)

**Files:**
- Create: `ui/tests/e2e/happy_path.spec.ts`
- Modify: `ui/package.json` (add Playwright)

Optional. Open `/`, choose `consent=full`, type `"Stockton-on-Tees"`,
submit. Land on `/place/ltla24:E07000223`. Assert at least one
indicator card visible and at least one source citation.

If Playwright setup is brittle on the current dev box, skip this task
and rely on the Block G/H Vitest tests + the manual smoke for the
Phase 2 tag. Moves to Phase 3 if skipped.

Commit: `test: phase 2 ui happy-path via Playwright`.

### Task 45: Tag `v0.3.0-phase-2`

**Steps:**

1. `make lint && make type && make test && make test-integration` all
   green.
2. `make up && make migrate && make seed-light` runs the stack with the
   new `ui` service and the capture middleware live.
3. Open `http://localhost:8088/` in a browser, submit a search, confirm
   the result page renders citations and the consent banner.
4. Run `make publish-corpus PERIOD=$(date -v -1m +%Y-%m)` against the
   seeded corpus, confirm three files materialise and the local git
   tag exists.
5. Update `STATE.md` and `PLAN.md` (Phase 2 done, Phase 3 next).
6. Tag and push:

```bash
git tag -a v0.3.0-phase-2 -m "phase 2: capture pipeline + sanitisation + minimal UI"
git push origin v0.3.0-phase-2
```

Commit: `docs: phase 2 complete — capture + UI live`.

---

## Done criteria for Phase 2

All green simultaneously:

- [ ] Every `POST /v1/tools/*` writes a `raw_record` + stub
      `question_record` in the same DB transaction.
- [ ] The background sanitiser produces a sanitised `question_record`
      within 2 seconds of the request, end-to-end. Background tasks are
      tracked in `app.state.background_tasks` (no GC drops).
- [ ] `corpus.question_record` rows have `review_status IN
      ('cleared','flagged','released')` after sanitisation completes;
      `pending` rows are re-queued at startup with a 4-way concurrency
      cap on spaCy.
- [ ] `POST /v1/capture/consent` issues session + consent + sector
      cookies; the `none` level skips capture entirely.
- [ ] `POST /v1/capture/feedback` updates `marked_useful` for the
      submitting session only.
- [ ] Sanitiser failures, retention-cron failures, and publication
      failures fire Resend alerts to `SOUNDINGS_ALERT_EMAIL`.
- [ ] `make publish-corpus` produces `corpus-YYYY-MM.csv.gz`,
      `corpus-YYYY-MM.jsonl.gz`, `manifest.json` in `./corpus/` and
      creates a local git tag `corpus-YYYY-MM`.
- [ ] Manifest contains a stable `catalogue_version`, the active
      `sanitisation_rules_version`, file SHA-256s, and the generator
      git sha.
- [ ] UI service serves `/`, `/search`, `/place/{id}`, `/about` end-to-end
      via Caddy. All routes are SSR; UI image builds offline.
- [ ] Cookies round-trip on UI → API calls via
      `credentials: "include"` + `CORS allow_credentials=True`.
- [ ] `/healthz` reports `capture` pipeline freshness and flips
      `degraded` on backlog.
- [ ] CI on `main` is green (PR job + nightly job).
- [ ] Tag `v0.3.0-phase-2` pushed.

---

## Deferred from Phase 2 (with explicit reasons)

| Deferred item | Why | Phase |
|---|---|---|
| `getStaticPaths` pre-rendering of LTLA/constituency pages | Build-time API dependency creates a CI fragility; SSR is fast enough on Mac mini. | 6 (polish) |
| Observable Plot charts | No time-series data until `get_trend` exists. | 3 |
| Backblaze B2 publication push | Local-first default; defer until bucket + keys exist. | 5 |
| Restricted Postgres roles for sanitiser/retention split | Migration 0004 already created `soundings_sanitiser`; further role split is hygiene, not correctness. | 5 |
| Ops UI for `flag_for_review` queue | psql-only acceptable while flag rate is low; revisit if > 5% records flag. | v1.5 |
| Hard-delete cron for permanent-orphan pending stubs | Edge case (sanitiser fail + raw retention pass); revisit if it accumulates. | 3 |

---

## What's next (preview, not in this plan)

**Phase 3** — Passthrough adapters for OHID Fingertips, DWP Stat-Xplore,
DfE Explore Education Statistics, data.police.uk. New tools:
`compare_places` (with percentile context across same-type peers) and
`get_trend` (time-series). The UI gets a comparison chart on
`/place/{id}` and a trend chart per indicator card (Observable Plot
integration finally lands).

**Open questions for Phase 2 implementation:**

1. Default consent level: spec §12.2 leaves this open; plan ships
   `minimal`. Worth user-testing whether `full` should default with
   prominent opt-down once we have any external users.
2. `flag_for_review` queue is psql-only in v1 (no ops UI); plan defers
   the human-review UI to v1.5. Acceptable risk if the multi-fire rate
   stays low; revisit if > 5% of records flag.
3. B2 publication push: plan defers per global "ask before hosted
   service". Add Task 28b when the bucket + keys exist.
4. spaCy model upgrade: `_sm` is the default; `_trf` improves recall on
   uncommon names but adds ~500MB to the image. Revisit after first
   public corpus release if precision is unacceptable.
5. UI testing strategy: Vitest for components, Playwright optional for
   one e2e. If Playwright setup is brittle, the UI e2e moves to Phase 3
   and the Phase 2 tag relies on manual smoke + Vitest coverage.

*End of Phase 2 plan.*

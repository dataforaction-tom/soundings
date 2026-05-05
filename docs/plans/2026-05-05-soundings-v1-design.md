# Soundings v1 — Implementation design

**Date:** 2026-05-05
**Author:** Tom (with Claude Code, brainstorming session)
**Status:** Approved, ready for implementation planning
**Source specs:** `v1-orchestration-and-capture.md`, `v1.5-just-in-time-interfaces.md`, `v2-context-layer.md`, `v3-contribution-layer.md`, `indicators.yaml`, `soundings.yaml`

This document is the build-time design for Soundings v1. It does not replace the spec — it commits to specific implementations of the spec's contracts and pins down the choices that the spec leaves open.

---

## 0. Decisions made during brainstorming

| Decision | Choice |
|---|---|
| Build scope | Full v1 per the spec — six tools, capture, thin UI, Mac mini deployment |
| Stack | Python/FastAPI + MCP Python SDK + Postgres 16 + PostGIS + Astro 4, per spec §2 |
| Hosting | Existing Mac mini in NE England, behind existing Cloudflare Tunnel (additive ingress rule, no new tunnel) |
| Dev workflow | A3 — Windows for inner-loop work + Mac mini for staging/deploy; both push to GitHub |
| Repos | Public `soundings` (AGPL-3.0 server, CC0 schema, CC BY 4.0 specs) + private `soundings-ops` for secrets/deployment |
| Indicator catalogue | The shipped `indicators.yaml` is authoritative; revised additively |
| Testing bias | Recorded fixtures (`pytest-vcr`) for unit tests + nightly live-API suite |
| Data flow | **Hybrid (Approach 3):** loader-mode for slow-changing/bulk sources, pass-through-with-TTL-cache for live APIs |
| Cache-status semantics | `live` / `cached` / `stale` set by base classes, never silently approximated |
| Failure isolation | Adapter failures degrade tool responses with `caveats`; geography failures fail the request |
| Capture pipeline | Two-step write: raw first (30-day retention), sanitised out-of-band, replayable on rule change |
| Default consent level | `minimal` (per spec) |
| Deploy verb | Manual `make ship` first; auto-pull added later |
| v1 alerting | Email-on-failure via Resend only; no Prometheus/Loki instance, only the endpoints |

---

## 1. Repo and runtime topology

Single public monorepo `soundings/`. Companion private `soundings-ops/` holds secrets and deployment-only configs.

```
soundings/
├── catalogue/
│   ├── indicators.yaml                     ← authoritative; relocated from root
│   ├── sources.yaml                        ← adapter mode + cadence per source
│   └── sanitisation.yaml                   ← thresholds + redaction rules
├── server/
│   ├── soundings/
│   │   ├── mcp/                            ← MCP tool registrations + Pydantic schemas
│   │   ├── http/                           ← FastAPI routes (mirror of MCP for the UI)
│   │   ├── geography/                      ← spine: postcode lookup, level conversion
│   │   ├── adapters/                       ← one module per source (loader + passthrough)
│   │   ├── catalogue/                      ← loader/validator for indicators.yaml
│   │   ├── capture/                        ← corpus writer + sanitisation pipeline
│   │   ├── cache/                          ← source_cache helpers, TTL policy
│   │   ├── orchestrator.py                 ← composes adapter calls per tool
│   │   ├── db/                             ← async SQLAlchemy 2 + Alembic migrations
│   │   ├── loader/                         ← APScheduler entrypoint for loader service
│   │   └── core/                           ← config, errors, source_ref helpers
│   ├── tests/                              ← unit + integration (live, nightly)
│   └── pyproject.toml                      ← uv-managed, py 3.12
├── ui/                                     ← Astro 4, server-rendered
│   ├── src/pages/{index,place/[id],about}.astro
│   └── src/lib/api.ts                      ← thin client to FastAPI HTTP mirror
├── infra/
│   ├── docker-compose.yml                  ← postgres + server + loader + ui + caddy
│   ├── Dockerfile.server                   ← shared image for server + loader
│   ├── Dockerfile.ui
│   ├── Caddyfile                           ← path routing only, no TLS termination
│   └── seed/                               ← `make seed` jobs
├── docs/
│   ├── plans/                              ← brainstorm + implementation plans
│   ├── adr/                                ← lightweight architecture decision records
│   ├── runbooks/                           ← restore, deploy, oncall (minimal)
│   └── *.md                                ← v1, v1.5, v2, v3 specs (relocated from root)
├── examples/                               ← v2 profile examples (forward-looking)
├── scripts/                                ← dev helpers, fixture recorders
├── CLAUDE.md / PLAN.md / STATE.md / MISTAKES.md / HANDOFF.md
├── LICENSE-AGPL-3.0  /  LICENSE-CC0  /  LICENSE-CC-BY-4.0
└── README.md
```

### Runtime processes

```
Cloudflare → existing tunnel → caddy → ui (Astro :4321) and server (FastAPI :8000)
                                                    │
                                                    ▼
                                              postgres :5432

separate process: loader (APScheduler in same image as server)
```

Four core services + one scheduler:
- `postgres` (PostGIS 16)
- `server` (FastAPI + MCP SDK; MCP at `/mcp`, HTTP at `/v1/*`)
- `loader` (same image, runs `python -m soundings.loader.run`)
- `ui` (Astro)
- `caddy` (path routing only — TLS terminates at Cloudflare edge)

### Tooling

- Python 3.12, `uv` for deps
- `httpx` for upstream calls; `aiolimiter` per-source token buckets
- SQLAlchemy 2 async + Alembic
- Pydantic v2 for tool I/O schemas (single source of truth, no yaml indirection)
- `pytest` + `pytest-vcr`; `ruff`; `mypy --strict`; `pre-commit`
- Astro 4 + Observable Plot (server-rendered SVG)

---

## 2. Postgres schema

Five logical schemas in one Postgres database.

### `geography`
- `place(id pk, type, code, name, valid_from, valid_to, geom)` — canonical place spine
- `place_hierarchy(child_id, parent_id)` — nested-set for "what contains this"
- `postcode(postcode pk, lsoa21, msoa21, ltla24, utla24, ward24, westminster_constituency_24, region, country, retrieved_at)`
- `code_change(old_code, new_code, change_type, effective_date, notes)` — boundary history

### `catalogue`
Loaded from `indicators.yaml` and `sources.yaml` at startup; not user-mutable at runtime.
- `indicator(key pk, label, description, unit, higher_is, source_id, available_at[], refresh_cadence, caveats jsonb, related_keys[], catalogue_version)`
- `source(id pk, label, publisher, publisher_url, dataset_url, licence, mode, refresh_cadence, rate_limit jsonb)`

### `data` (loader-mode source storage)
- `indicator_value(place_id, indicator_key, period, value, value_text, source_id, retrieved_at, loader_run_id, caveats, pk(place_id, indicator_key, period))`
- `trend_point(place_id, indicator_key, period, value, revised, source_id, retrieved_at, pk(place_id, indicator_key, period))` — separate because `get_trend` is hot
- `organisation(id pk, name, classification[], registered_address_place_id, source_id, retrieved_at, raw jsonb)`
- `organisation_operates_in(organisation_id, place_id, pk both)`
- `grant_record(id pk, funder_id, recipient_org_id, amount, currency, awarded_on, purpose, beneficiary_place_ids[], source_id, retrieved_at)`
- `loader_run(id uuid pk, source_id, started_at, finished_at, status, rows_written, notes)` — drives `cache_status: stale`

### `cache` (passthrough TTL)
- `source_cache(source_id, cache_key, payload jsonb, retrieved_at, expires_at, pk(source_id, cache_key))`

### `corpus`
- `question_record(id uuid pk, timestamp, session_id, consent_version, capture_level, natural_language_question, tool_called, tool_inputs_redacted jsonb, geography_referenced jsonb, indicators_returned[], sources_used[], result_status, error_class, asker_sector, asker_purpose, marked_useful, composed_artefact jsonb, gap_signals[], derived_from_question_id)` — v1.5 fields nullable
- `raw_record(id uuid pk → question_record(id), raw_payload jsonb, created_at)` — locked-down role grants, 30-day retention

Migrations via Alembic. Initial migrations are stable contracts post-v1.0; only additive changes thereafter.

`make seed` order: catalogue load → geography spine → loader sources. Idempotent and re-runnable. ~1 hour on a fresh Mac mini, dominated by ONS boundary downloads.

---

## 3. Source adapter pattern

### Single protocol, two base classes

Every adapter implements:

```python
class SourceAdapter(Protocol):
    source_id: str
    mode: Literal["loader", "passthrough"]

    async def fetch_indicator(
        self, indicator_key: str, place_id: str, period: str | None
    ) -> IndicatorValue | None: ...
    async def list_available_indicators(self) -> list[str]: ...
    def get_source_ref(self, retrieved_at, cache_status) -> SourceRef: ...
```

`PassthroughAdapter` base class handles cache lookup, TTL, retries, rate limiting, and `SourceRef` construction — subclasses only implement the upstream call and the response → `IndicatorValue` mapping.

`LoaderAdapter` base class reads from Postgres `data.*` tables; subclasses implement the periodic `load(run_id)` method called by the loader service.

### Cache-status rules

- `live` — passthrough hit upstream, fresh payload this request.
- `cached` — passthrough served within TTL, OR loader read served within `refresh_cadence`.
- `stale` — passthrough TTL expired and upstream is unreachable, served prior value as fallback. OR loader read returned a value whose latest `loader_run.finished_at` is older than `refresh_cadence × 1.5`.

Stale data is allowed; *hidden* degradation is not — `cache_status` propagates to the user.

### Adapter assignments (v1)

```yaml
# catalogue/sources.yaml — pinned in this design
- ons.geography:        loader,      quarterly
- ons.census2021:       loader,      yearly             # deviation from spec — Census is a snapshot
- mhclg.imd2019:        loader,      monthly (cron 0 3 1 * *)
- mhclg.live_tables:    loader,      weekly
- charity_commission:   loader,      nightly
- 360giving:            loader,      weekly Sunday
- postcodes.io:         passthrough, 30 days TTL
- dwp.statxplore:       passthrough, 24h TTL
- ohid.fingertips:      passthrough, 24h TTL
- ons.aps:              passthrough, 24h TTL
- dfe.explore:          passthrough, 24h TTL
- police_uk:            passthrough, 24h TTL
- find_that_charity:    passthrough, 7-day TTL
```

### Rate limits and retries

- One `httpx.AsyncClient` per adapter; per-source `aiolimiter` token buckets.
- Retry policy: 3 attempts, exponential backoff (1s/4s/16s) on 5xx + connection errors. No retry on 4xx.
- Per-process concurrency caps: e.g. 4 concurrent calls to Stat-Xplore, 8 to police.uk.

### Failure isolation

- Adapter exceptions caught at orchestrator boundary → `result_status: "partial"` with failed source named.
- `compare_places` / `get_indicators` return what they could fetch; missing values become `caveats` entries.
- Geography spine failures (the one exception) fail the whole request — spec §3 "no silent approximation".

### Per-adapter testing

- Unit: `pytest-vcr` cassettes under `server/tests/cassettes/<source_id>/`. Required cases per adapter: happy path, no-data, rate-limited, 5xx.
- Live: `pytest -m live` suite hits real upstreams against a stable fixture place (`ltla24:E07000223` Stockton-on-Tees). Nightly cron in CI; failures alert but don't block PRs.

---

## 4. MCP tools, orchestration, and UI

### Tool registration — single implementation, two transports

Tools live in `server/soundings/mcp/tools.py`. Each is a thin Pydantic-typed function decorated with `@mcp.tool()` AND mounted as a FastAPI route under `/v1/tools/{tool_name}`. The MCP server is mounted on the same FastAPI app at `/mcp`.

The six v1 tools per spec §4: `find_place`, `get_place_profile`, `get_indicators`, `compare_places`, `get_trend`, `find_organisations_in_place`.

CORS locked to the UI origin only.

### Orchestrator behaviours

| Tool | What it does |
|---|---|
| `find_place` | Geography spine only — postcode → `postcode` table; free text → fuzzy match against `place.name`, ranked by hierarchy depth; `geography_types` filter at SQL level |
| `get_place_profile` | Catalogue lookup for `include` domains → indicator keys → adapter fan-out via `asyncio.gather` → aggregated `IndicatorValue[]`; per-domain failures become `caveats` |
| `get_indicators` | Catalogue lookup per key → adapter dispatch by `source_id` → concurrent fan-out → wide/tall format post-shape |
| `compare_places` | `get_indicators` × N places → percentile/rank computation against parent geography (default `comparison_basis: "percentile"` against same-type peers) |
| `get_trend` | Single adapter call with period range; `trend_point` (loader) or upstream time-series endpoint (passthrough); series-break notes from `indicator.caveats` filtered to time-related entries |
| `find_organisations_in_place` | `data.organisation_operates_in` JOIN; `funded_only` joins `grant_record`; no live calls |

Concurrency: `asyncio.gather(return_exceptions=True)`. Tool-call soft budget 10s; a passthrough that would breach it returns prior `cache_status: stale` or a `caveats` entry if no prior cache exists.

`SourceRef` deduplicated by `(source_id, retrieved_at_minute)` so the UI can cite once per source.

### HTTP routes

```
GET  /healthz
GET  /v1/tools                         ← list tools + JSON schemas
POST /v1/tools/find_place
POST /v1/tools/get_place_profile
POST /v1/tools/get_indicators
POST /v1/tools/compare_places
POST /v1/tools/get_trend
POST /v1/tools/find_organisations_in_place
GET  /v1/sources                       ← sources.yaml + last loader_run per source
GET  /v1/catalogue/indicators
POST /v1/capture/feedback              ← marked_useful for a question_record
```

### UI — three pages, server-rendered

- `/` — search box + consent banner. Submission produces structured response with citations and a `<details>` "data behind this" panel showing tool calls.
- `/place/[id]` — auto-generated profile. **Pre-rendered at build time for LTLAs and Westminster constituencies (~700 pages); LSOA renders on-demand.** Cards per indicator domain, citations, last-updated dates. Bar/line charts via Observable Plot, server-rendered SVG.
- `/about` — what Soundings is, capture explainer, links to corpus downloads, GitHub repo, spec docs.

Session cookie: `session_id` (rotating UUID, no persistent identity) + `consent_level`. Set only on first interaction with the consent banner — no `Set-Cookie` before consent UI is shown.

The UI cannot do anything an external client can't.

### Error shape

```json
{
  "error": {
    "code": "GEOGRAPHY_NOT_FOUND" | "UPSTREAM_TIMEOUT" |
            "INDICATOR_NOT_AVAILABLE_AT_LEVEL" | "RATE_LIMITED" | "INTERNAL",
    "message": "...",
    "details": { "place_id": "...", "indicator": "..." }
  }
}
```

`INDICATOR_NOT_AVAILABLE_AT_LEVEL` is the explicit "refuse rather than silently approximate" error.

---

## 5. Capture pipeline

### Two-step write

1. **`raw_record`** — pre-sanitisation snapshot. Written first, synchronously, in the same DB transaction as the response. Schema with restricted role grants (sanitiser reads only; retention cron deletes only). 30-day retention.
2. **`question_record`** — sanitised, publishable record. Written by the sanitiser, running out-of-band as `asyncio.create_task` from the FastAPI middleware. Failure path: raw record stays, sanitiser failure logged for review; replayable.

This guarantees no tool call is ever uncaptured even if the sanitiser is buggy. Also enables replay against the 30-day raw window when sanitisation rules change.

### Pipeline (ordered)

```python
PIPELINE = [
    StripUnitPostcodes,
    StripFineGeographyInFreeText,           # finer than MSOA in nat-lang question
    StripPersonalNamesViaNER,                # spaCy en_core_web_sm; trf fallback
    StripSmallOrgNames,                      # threshold from sanitisation.yaml
    NormaliseAskerPurpose,                   # whitespace + length cap
    ValidateConsentLevel,                    # "none" → discarded
]
```

If two or more rules fire on a single record → `flag_for_review` queue, not auto-published. Human releases via psql in v1; ops UI deferred.

Small-org threshold: charities with income < £100k from CC extract treated as identifiable in context. Threshold lives in `catalogue/sanitisation.yaml`.

### Consent levels (per spec §8.2)

- `full` — natural-language question + asker fields captured. Pipeline runs.
- `minimal` (**default**) — structured fields only. Natural-language question discarded at middleware boundary; never enters raw_record.
- `none` — no records written. Session_id rotates for rate-limit purposes only, not persisted.

### Publication

Monthly export job:
1. Snapshot transaction over corpus tables.
2. Filter: `consent_version IS NOT NULL AND capture_level IN ('full','minimal') AND review_status = 'cleared'`.
3. Write `corpus-YYYY-MM.csv.gz` (flattened wide) and `corpus-YYYY-MM.jsonl.gz` (full nested).
4. SHA-256 manifest including catalogue version + sanitisation rules version active during the period.
5. Push to Backblaze B2 public bucket; `/about` reads bucket index.
6. Tag git commit `corpus-YYYY-MM` for reproducibility.

License: CC BY 4.0, baked into both files.

### Abuse guards on `asker_purpose`

- 280-character cap.
- Per-session full-consent rate limit: 60 captured records/hour; further records drop to `minimal`.
- Sanitisation runs on `asker_purpose` too — same NER, same redaction.

### Backups

- Nightly `pg_dump` of `corpus` + `data` schemas, `age`-encrypted, shipped to Backblaze B2.
- Geography + catalogue **not** backed up — reproducible from `make seed` (~1 hour).
- Restore drill documented in `docs/runbooks/restore.md`; rehearse once before launch + quarterly thereafter.
- Two B2 buckets, separate accounts, weekly verify-from-cold restore to scratch DB.

### Deliberate non-additions

- **No Redis or message broker.** `asyncio.create_task` for background sanitisation; startup hook re-queues unsanitised records if the process died mid-way.
- **No streaming export.** Monthly batch only.
- **No "delete my data" UI.** No persistent identity → nothing to delete. `/about` states this explicitly.

---

## 6. Deployment, ops, Mac mini

### Docker Compose stack

Five services:

| Service | Image | Notes |
|---|---|---|
| `postgres` | `postgis/postgis:16-3.4` | volume `pgdata` |
| `server` | built from `Dockerfile.server` | FastAPI + MCP, `127.0.0.1:8000` |
| `loader` | same image as `server` | `python -m soundings.loader.run`; APScheduler |
| `ui` | built from `Dockerfile.ui` | Astro, `127.0.0.1:4321` |
| `caddy` | `caddy:2` | path routing only, `127.0.0.1:8088:80` |

`server` and `loader` share an image — same code, different process roles, single `docker compose build`.

### Caddyfile

```caddy
:80 {
    handle /mcp/* { reverse_proxy server:8000 }
    handle /v1/*  { reverse_proxy server:8000 }
    handle        { reverse_proxy ui:4321 }
}
```

### Cloudflare Tunnel — additive ingress only

Existing `cloudflared` on the Mac mini gets one new ingress rule for `soundings.<chosen-domain>` pointing at `http://localhost:8088`. No changes to existing tunnel or to other services on it. Exact edit to `~/.cloudflared/config.yml` to be confirmed in implementation plan once we know:

- Existing tunnel hostname pattern (to avoid collisions).
- Already-bound localhost ports (default plan: 5432/8000/4321/8088).
- Whether `cloudflared` runs as `launchd` service or under user account.

### Secrets

- Stored in private `soundings-ops/`, encrypted with `age`.
- Mac mini holds `age` private key in `~/.config/sops/age/keys.txt` (root-only).
- `.env` generated locally by `make decrypt-env`; git-ignored.
- v1 keys: Charity Commission, Anthropic (placeholder for v1.5), Backblaze B2, Postgres credentials.
- `.env.example` in public repo lists every variable name with a comment, no values.

### Make targets — operator interface

```
make seed           # full one-off seed of geography spine + catalogue + bulk loaders
make seed-light     # subset for dev (single LTLA's worth of data)
make migrate        # alembic upgrade head
make backup         # encrypted pg_dump, push to B2
make restore TS=…   # interactive restore from B2
make publish-corpus # monthly CSV+JSONL, push to B2, tag commit
make test           # unit tests with cassettes
make test-live      # nightly live-API suite (CI cron only by default)
make decrypt-env    # pull soundings-ops, decrypt to .env
make ship           # build, push to GHCR, ssh mac-mini && pull && up
```

### Branch and deploy strategy

- `main` always deployable.
- Feature branches → PR → merge to `main`.
- GitHub Action on `main` builds + pushes images to GHCR.
- `make ship` from a dev machine triggers SSH-driven pull on the Mac mini for v1.
- Auto-pull cron added later, gated on a sentinel tag, only after several manual ships.

### Observability

- Logs: `structlog` JSON to stdout; `docker compose logs -f` for dev. No Loki sidecar in v1.
- Metrics: Prometheus-compatible `/metrics` endpoint on server (latency per tool, adapter-call counts, cache hit rate, capture pipeline throughput). No Prometheus instance in v1 — endpoint exists for v1.5+.
- Health: `/healthz` checks Postgres, catalogue load, last successful loader-run age. Cloudflare can poll.
- Alerts: email-on-failure via Resend only. Triggers: failed loader run, sanitiser failure, monthly publication failure, backup failure.

### Resource envelope (Mac mini)

| Service  | RAM steady | RAM peak |
|---|---|---|
| postgres | 2 GB | 4 GB during seed |
| server   | 400 MB | 1.5 GB |
| loader   | 400 MB | 2 GB during loader runs |
| ui       | 200 MB | 400 MB |
| caddy    | 50 MB | 50 MB |
| **Total** | **~3 GB** | **~8 GB during seed** |

Disk: ~10 GB Postgres at full v1 data load. Comfortably inside spec §10's 50 GB budget.

---

## 7. What this design does NOT do (and where it's deferred)

| Excluded from v1 | Where it lands |
|---|---|
| Just-in-time dashboards, narrative briefs, `/asks` view | v1.5 |
| Auth/identity for users | v2 (with org context layer) |
| Org context profiles | v2 |
| Contributed observations from orgs | v3 |
| Vector store for similar questions | v1.5 if Postgres FTS+trigram isn't enough |
| Predictive modelling, forecasting, "places like mine" | Out of scope |
| Loki / Prometheus / PagerDuty | Endpoints ready, instances v1.5+ |
| "Delete my data" UI | Not applicable — design has no persistent identity |
| UK-wide indicator parity | Coverage gaps are documented in `indicators.yaml` per spec §11 |

---

## 8. Open questions tracked into implementation

1. **GitHub org name** — needed before repo creation. Likely `dataforaction-tom` or a Good Ship org.
2. **Final hostname for `soundings.*`** — confirm against existing tunnel routes.
3. **Existing tunnel layout** — hostnames, bound localhost ports, `cloudflared` runtime owner.
4. **API key registrations to do at adapter time:** Nomis, DWP Stat-Xplore, DfE Explore Education Statistics. (User already has Charity Commission, 360Giving, Anthropic.)
5. **Indicator naming convention:** spec §12.1 — `population.total` vs `pop.total`. Defer to whatever `indicators.yaml` already uses; lock at v1.0.
6. **Default capture level:** `minimal` for v1; revisit after public corpus releases reveal usage patterns.

---

## 9. Build sequence (pinned from spec §13)

| Phase | Weeks | Deliverable |
|---|---|---|
| 0 | 1 | Repo, CI, Compose scaffolding, Postgres schema, geography spine end-to-end (postcode → all geographies). |
| 1 | 2–3 | Adapters: postcodes.io, ONS Census 2021 (Nomis), MHCLG IMD. Tools: `find_place`, `get_place_profile`, `get_indicators`. |
| 2 | 2 | Capture layer + sanitisation. Corpus writing for every call. Minimal `/` and `/place/[id]` UI. |
| 3 | 2 | Adapters: Fingertips, DWP Stat-Xplore, DfE, police.uk. Tools: `compare_places`, `get_trend`. |
| 4 | 1–2 | Adapters: Charity Commission, 360Giving, Find That Charity. Tool: `find_organisations_in_place`. |
| 5 | 1 | First monthly corpus release. Documentation pass. |
| 6 | 1 | Public soft launch on Mac mini. Feedback gathering for v1.5. |

Total: 10–12 weeks of focused build. Implementation plan detailing tasks per phase to be produced next via the `writing-plans` skill.

---

*End of design.*

# Natural-language ask interface — design

**Date:** 2026-05-31
**Status:** Draft for review
**Phase:** Phase 6 (reoriented from "new data sources" to depth on the existing corpus — see `docs/plans/2026-05-24-phase-6-data-sources-plan.md` for the paused predecessor).

## Why this exists

The MCP/HTTP tool surface is excellent for agents and developers. It is not a product for a journalist, a commissioner, or a charity trustee — those users want to ask a plain-English question about a UK place and get a brilliant, well-sourced answer. Today the UI offers a place picker and pre-set domain cards; there is no path from "tell me about Stockton" to a composed, narrative answer.

This design adds that path. A single shareable answer page per question, narrative-led with embedded indicator cards and charts, backed by Claude in tool-use mode against the existing tools.

## Goals

- A natural-language entry point — both from the homepage and from a place page — that produces a single, shareable answer page per question.
- The answer is composed: prose interleaved with the right indicator cards, trend sparklines, comparison charts, and (where relevant) civil-society organisations.
- First-class structured modes: **summary**, **compare**, **insights**, **open**. The free-text question is the default; the modes are chips that send a canned query for the current context.
- Insights are reproducible: a deterministic detector picks out extreme percentiles, peer divergences, and trend reversals; Claude narrates over the detected signals.
- The new endpoint is captured by the existing corpus pipeline. Sanitisation, consent, sources, and `cache_status` provenance are preserved end to end.

## Non-goals

- No chat thread / conversation persistence. Each question is independent.
- No client-side LLM call. The Anthropic API key never leaves the FastAPI server.
- No new MCP transport, no new tool wire formats beyond `compose_answer` and `detect_insights`.
- No agentic write actions — Claude can only read via the existing tools.
- No general web search. The model only sees what our tools return.
- No multi-place batch answers ("compare every LTLA in the North East") — bounded to the existing `compare_places` budget of up to 10 explicit peers.
- No new ingestion. The "make the data we have shine" pivot explicitly defers Phase 6 data-source work.

## Architecture & data flow

```
┌──────────────────────────────────────────────────────────────────┐
│  Astro UI                                                         │
│  ┌──────────────┐   ┌──────────────────┐   ┌──────────────────┐  │
│  │   /  (home)  │   │ /place/[id]      │   │ /ask?q=…&p=…     │  │
│  │  AskBox      │   │ AskBox           │   │ Answer page      │  │
│  │  + chips     │   │ + chips          │   │ streaming blocks │  │
│  └──────┬───────┘   └────────┬─────────┘   └────────▲─────────┘  │
│         │  submit            │  submit              │  SSE       │
│         └──────────┬─────────┴──────────────────────┘            │
└────────────────────┼──────────────────────────────────────────────┘
                     │  POST /v1/ask {query, place_id?, mode?}
                     ▼
┌──────────────────────────────────────────────────────────────────┐
│  FastAPI                                                          │
│  /v1/ask  ──────►  AskOrchestrator                               │
│                      │                                            │
│                      │  Claude tool-use loop (anthropic SDK):     │
│                      │   • find_place                             │
│                      │   • get_place_profile                      │
│                      │   • compare_places                         │
│                      │   • get_trend                              │
│                      │   • find_organisations_in_place            │
│                      │   • detect_insights        (NEW)           │
│                      │   • compose_answer({blocks}) ← terminal    │
│                      ▼                                            │
│                  ToolDispatcher (in-process)                      │
│                  reuses the same Python handlers that back        │
│                  /v1/tools/* and the MCP registrations            │
│                      │                                            │
│                      ▼                                            │
│            SSE: status / block / sources / done / error           │
└──────────────────────────────────────────────────────────────────┘
```

Key shape:

- A single agentic loop. Claude calls data tools any number of times; the loop terminates on `compose_answer`.
- Tool execution is in-process — no HTTP round-trip back to the server's own endpoints. The same handler functions back `/v1/tools/*`, the MCP registrations, and the ask dispatcher.
- The protocol with the UI is the typed `compose_answer` block array.
- SSE streams from FastAPI to Astro to the browser. The Astro `/ask` page renders blocks as they arrive.
- The existing capture middleware (sanitisation, consent, corpus capture) wraps `/v1/ask` like every other tool route.

## Components

### Server-side (`server/soundings/`)

| Component | Path | Job | Depends on |
|---|---|---|---|
| `AskOrchestrator` | `ask/orchestrator.py` | Runs the Claude tool-use loop. Streams events to a callback. Decides when to terminate (on `compose_answer`). Enforces max-iterations. | `anthropic` SDK, `ToolDispatcher` |
| `ToolDispatcher` | `ask/dispatcher.py` | Maps an Anthropic `tool_use` block to the right in-process Python handler. Returns serialised results. | All existing tool handlers in `tools/` |
| `compose_answer` schema | `ask/blocks.py` | Pydantic models for the typed blocks. Single source of truth for both the Anthropic tool schema and the SSE payload. | None |
| `detect_insights` tool | `tools/detect_insights.py` | Pure SQL-driven detector: extreme percentiles, peer divergence, trend reversals. Returns `InsightSignal`s for Claude to narrate over. | `data.indicator_value`, `geography.place` |
| `/v1/ask` route | `http/ask.py` | HTTP endpoint. Validates input, passes through capture middleware, opens an SSE response, runs the orchestrator. | `AskOrchestrator`, capture middleware |
| `SystemPromptBuilder` | `ask/prompts.py` | Builds the system prompt. Knobs: `mode` (`open`/`summary`/`compare`/`insight`), pinned `place_id`. | None |
| `ask` MCP registration | `mcp/registration.py` (extend) | Exposes `ask` as an MCP tool — MCP clients can call the orchestrator. Same handler. | `/v1/ask` route logic |

### UI-side (`ui/src/`)

| Component | Path | Job | Depends on |
|---|---|---|---|
| `AskBox` | `components/AskBox.astro` | Single text input + three mode chips (Summary / Compare / Surprise me). Submits to `/ask?q=…&place_id=…&mode=…`. Reused on `/` and `/place/[id]`. | None |
| `/ask` page | `pages/ask.astro` | Reads URL params; renders a client-only `AnswerSurface` island that opens SSE to `/v1/ask` and appends blocks as they stream in. Shareable URL is the question. The page itself is SSR for the shell (head, header, footer); the streaming region is `client:only="vanilla"` (or Preact island if we want JSX) because Astro SSR cannot stream into a partially-rendered DOM. | `AnswerStream`, `AnswerBlock` |
| `AnswerStream` | `lib/answer_stream.ts` | SSE client. Parses events; emits an ordered list of typed blocks. Pure TS, unit-testable. | None |
| `AnswerBlock` | `components/AnswerBlock.astro` (or `.ts` if rendered from the client island) | Switch on `block.type` → renders the right child component. Existing `IndicatorCard`, `IndicatorChart`, `CompareChart`, `OrganisationCard` reused unchanged — but they must be importable from the client island. Where an Astro component can't render client-side, a thin TS twin renders the same DOM (kept in sync by snapshot test). | All existing card/chart components |
| `InsightCallout` | `components/InsightCallout.astro` | Severity-coloured callout for `insight-callout` blocks. | Existing design tokens |

## The `compose_answer` block schema

```python
# server/soundings/ask/blocks.py

class TextBlock(BaseModel):
    type: Literal["text"]
    markdown: str          # rendered with a sanitised markdown lib client-side

class IndicatorCardBlock(BaseModel):
    type: Literal["indicator-card"]
    indicator_key: str
    place_id: str
    period: str | None = None    # None = latest fetched; otherwise must match a fetched period

class TrendChartBlock(BaseModel):
    type: Literal["trend-chart"]
    indicator_key: str
    place_id: str
    caption: str | None = None

class CompareChartBlock(BaseModel):
    type: Literal["compare-chart"]
    indicator_key: str
    place_ids: list[str]                  # 2..10
    basis: ComparisonBasis = "percentile" # matches existing compare_places

class OrganisationsBlock(BaseModel):
    type: Literal["organisations"]
    place_id: str
    limit: int = 5

class InsightCalloutBlock(BaseModel):
    type: Literal["insight-callout"]
    severity: Literal["notable", "extreme"]
    headline: str
    indicator_key: str | None = None
    place_id: str | None = None
    evidence: str         # one-line "why this matters" — Claude-authored

AnswerBlock = Annotated[
    TextBlock | IndicatorCardBlock | TrendChartBlock | CompareChartBlock
    | OrganisationsBlock | InsightCalloutBlock,
    Field(discriminator="type"),
]

class ComposeAnswerArgs(BaseModel):
    blocks: list[AnswerBlock]
```

**Resolution and validation**

The orchestrator keeps a fetch cache during the loop. After every successful data tool call, results are indexed by `(indicator_key, place_id)` or, for comparisons, `(indicator_key, frozenset(place_ids))`. When Claude calls `compose_answer`, each block referencing data is resolved against the cache. If a reference misses, the server returns a tool error — Claude can recover by calling the missing data tool and resubmitting.

Hard caps:
- **20 blocks total** per answer.
- **6 visual blocks** per answer (everything that isn't `text`).
- These keep the page from becoming a dump.

**Citations are implicit, not a block**

Every `IndicatorValue` / `Comparison` / `Trend` / `OrganisationRef` carries a `SourceRef`. As the loop runs, the orchestrator deduplicates `SourceRef`s touched and appends them to the SSE stream as a final `{type:"sources", sources:[…]}` event. The UI renders them in a footer below the blocks. Claude does not track citations.

## SSE wire protocol

```
{ type: "status",  message: "Looking up Stockton-on-Tees…" }   # per-tool-call narration
{ type: "block",   block: {…} }                                # one per block in compose_answer
{ type: "sources", sources: [SourceRef, …] }                   # final citations
{ type: "done" }                                               # terminator
{ type: "error",   message: "…" }                              # any failure
```

The `block` events are emitted as each block in the streamed `compose_answer` tool call completes — we don't wait for the full args. The Astro client appends in order and renders incrementally.

## Modes

Modes are knobs on the system prompt; they all use the same `/v1/ask` endpoint and the same answer renderer.

| Mode | What the chip sends | System prompt emphasis |
|---|---|---|
| `open` (default, free text) | Whatever the user typed | Generalist: pick whichever tools fit the question. |
| `summary` | `"Summarise <place_name>"` (place pinned from context) | Breadth across domains; one indicator card per major domain; close with a short narrative paragraph per section. |
| `compare` | `"How does <place_name> compare to its peers?"` | Always include at least one `compare-chart`; ground narrative in percentile framing; resolve peers via `compare_places`'s same-type peer universe. |
| `insight` | `"What's surprising about <place_name>?"` | Lead with the deterministic signals from `detect_insights`; one `insight-callout` per signal, ordered by severity; narrative explains the "so what". |

Modes are non-sticky — they're a per-request hint. The chip is a discoverability and pre-fill aid; the model is allowed to flex if the user's free text expresses a different intent.

**Chip behaviour by context**

- **Place page (`/place/[id]`)**: chips have a pinned `place_id`. Clicking a chip submits immediately with the canned query above.
- **Homepage (`/`)**: there is no pinned place. Chips focus the input and prefill a placeholder of the form `"Summarise <place name>"`, `"How does <place name> compare to its peers?"`, `"What's surprising about <place name>?"`. The user types the place name (or a postcode) and submits. The mode is preserved as a URL param.

Modes never make a request without a usable target — either a pinned `place_id` or a query string Claude can resolve with `find_place`.

## Insight detection

`detect_insights` is a pure SQL-driven server tool. Inputs: `place_id`, optional `indicator_keys` filter. Outputs: list of `InsightSignal { indicator_key, severity, kind, evidence_payload }`. Kinds:

- **`extreme_percentile`** — place's value is in the top or bottom decile of same-type peers. `severity="extreme"` when ≤5th or ≥95th percentile; `"notable"` between 5–10 / 90–95.
- **`peer_divergence`** — place's value is more than 1 standard deviation from the same-type median. Useful for indicators where the distribution isn't skewed.
- **`trend_reversal`** — the most recent point's signed slope is the opposite of the prior three points' average slope. Catches "this place was improving on X, now it's reversing."

Detection runs in a single CTE-driven query. No live API calls. Results are deterministic against a given snapshot of `data.indicator_value`.

Claude consumes the signals via the tool result; the `InsightCalloutBlock`s reflect Claude's editorial framing over the deterministic detections (not raw signal echoes).

## Streaming and error handling

**Latency budget.** Realistic v1: ~6–15 s end to end for an open-ended query. First `status` event within ~500 ms. First `block` event ~2–4 s in. Streaming hides the tail.

**Failure cases**

| What goes wrong | What the user sees |
|---|---|
| Place not resolvable | Status: "Couldn't find that place." Single `text` block explaining what kinds of place names work. Suggested-query chips below. |
| Upstream tool error (e.g., `compare_places` timeout) | Status event with the friendly tool error; Claude retries differently. After two failed retries the orchestrator returns a `text` block: "I could pull some data on Stockton but couldn't load peer comparisons just now." |
| `compose_answer` references missing data | Server returns tool error → Claude fetches and retries. Bounded by max-iterations. |
| Claude rate-limit / API error | `error` event surfaces; UI shows "Couldn't reach the model — please retry." URL stays the same so retry is a refresh. |
| Client disconnect mid-stream | Server tracks the SSE generator; on disconnect the orchestrator aborts the in-flight tool call (`asyncio.CancelledError`) and tears down the Anthropic stream. |
| Empty / junk query | 400 from `/v1/ask` before invoking Claude. |
| Out-of-scope question | The system prompt defines scope concretely: **questions answerable by the existing six data tools against UK places** (population, deprivation, economy, health, education, housing, crime, civil society). Anything else — weather forecasts, news, opinions, recommendations to act, advice — gets a single `text` block: `"Soundings answers from UK open data on places: indicators across population, health, housing, crime, civil society and more. I can't help with '<paraphrased subject>'. Want me to summarise a place or compare two?"` No tool calls; ~1 s. |

**Budgets**

- Max iterations of the tool loop: **12** (typical 3–4).
- Max parallel tool calls per iteration: **3** — Anthropic supports parallel tool use; we exploit it for "fetch profile + trends + organisations" in one round.
- Max tokens: **8k output**, **20k input**.
- Per-request hard timeout: **45 s** — the SSE generator raises `TimeoutError` and emits an `error` event.

## Dependencies and configuration

- New Python dep: `anthropic` (Tom-approved 2026-05-31).
- New env var: `ANTHROPIC_API_KEY` (server-side only).
- Default model: `claude-sonnet-4-6`.
- Optional override: `ASK_MODEL` env var.
- Local dev: API key supplied via `.env`. Live tests are nightly only and tagged `@pytest.mark.live`.

## Capture and consent

`/v1/ask` is captured by the existing middleware exactly like every other tool route.

- **Full consent**: question text + place_id + mode + tool calls + final block array all captured. Question text passes through the existing sanitisation pipeline before publication.
- **Minimal consent (default)**: structured fields only — mode, resolved place_id, tool call names, count of returned blocks. Question text not stored.
- **No consent**: nothing captured.

The corpus consumer downstream sees `tool_name = "ask"`, with a payload shape that includes the resolved `place_id`, mode, the ordered sequence of underlying tool calls, and the block array. No new sanitisation rules are required for v1.

## Testing

Same TDD pattern as every prior phase.

### Server

| Test file | Type | Covers |
|---|---|---|
| `test_ask_blocks.py` | Unit | Pydantic schema discrimination; rejects unknown `type`; required fields; cap enforcement (>20 blocks → validation error). |
| `test_ask_dispatcher.py` | Unit | Anthropic tool name → in-process handler mapping; result serialisation; tool errors surfaced cleanly. |
| `test_ask_orchestrator.py` | Unit, mocked Claude | Loop drives correctly off canned Claude responses; cache populated; missing references rejected; max-iterations honoured; status event order; client disconnect aborts cleanly. |
| `test_detect_insights.py` | Integration, test DB | Top/bottom-decile detection; peer divergence (>1 SD); trend reversal; empty result when no signals. |
| `test_ask_route.py` | Integration | SSE wire format; 400 on empty query; 422 on bad mode. Mocked Claude. |
| `test_ask_capture.py` | Integration | Capture middleware records `/v1/ask` requests at each consent level; sanitisation applies to the query text. |
| `test_ask_live.py` | `@pytest.mark.live` | One real-Claude call with `mode="summary"` for a seeded LTLA. Asserts at least one `text` block, at least one `indicator-card` block referencing seeded data, citations footer populated. Nightly only. |

### UI

| Test file | Covers |
|---|---|
| `tests/answer_stream.test.ts` | SSE parsing; chunked / partial events; order preservation; error surfacing. |
| `tests/answer_block.test.ts` | Each `block.type` maps to the right child component; unknown type renders a "skip" placeholder, not a crash. |
| `tests/ask_box.test.ts` | Mode chips populate query + mode in the URL; `place_id` is preserved when chips are clicked on `/place/[id]`. |

### Browser smoke (manual)

Gates the phase tag. Submit one query from `/`, one from `/place/[id]`, one of each mode chip. Same runbook pattern as Phase 3 / Phase 4 (`docs/runbook-phase-*-smoke.md`).

## What we are explicitly not building

- Conversation / thread state.
- Client-side LLM calls.
- New MCP tools beyond `ask`.
- New data sources (the deferred Phase 6 plan).
- Multi-place batch answers beyond `compare_places`'s 10-peer budget.
- Personalisation / saved questions / favourites — questions are sharable URLs, that's the persistence.

## Open follow-ups

- **Markdown rendering**: pick a sanitised markdown renderer for `TextBlock.markdown` (likely `marked` + `DOMPurify`). Decide in the implementation plan.
- **Insight detector tuning**: the percentile thresholds (5/10/90/95) and 1 SD divergence threshold are first-pass numbers. Revisit after the live smoke and a few real answers.
- **Mode-specific tools**: if `insight` mode would benefit from a tool that returns "the place's three biggest movers" specifically, we'd add it as a sibling to `detect_insights`. Not required for v1.
- **Streaming on the `/place/[id]` AskBox path**: v1 navigates to `/ask?q=…&place_id=…&mode=…`. A future iteration could inline the streamed answer below the chips without navigation. Out of scope here.
- **Caching identical questions**: same `(query, place_id, mode)` could hit a short TTL cache to make share-links snappy. Out of scope for v1; revisit if real traffic warrants it.

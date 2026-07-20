# Diagram briefs for "Building Soundings" blog post

Companion to `2026-07-20-building-soundings-draft.md`. Three core diagrams (matching the `[IMAGE n]` placeholders in the draft), one optional extra, and one optional header illustration. Each brief includes a ready-to-paste prompt for Claude design.

## Shared style notes (include with every prompt)

All diagrams should share one visual system so the post reads as a set:

- **Palette (The Good Ship brand):** warm cream background `#F5F0E8`; white `#FFFFFF` cards with `#E5DDD0` borders and rounded corners; navy `#2D3E50` for headings and primary text; body text `#5A6B7B`; sage green `#5B8A72` as the primary accent (arrows, highlights, the "question" colour); warm gold `#C9A84C` as a secondary accent (use sparingly — reserve it for the corpus/feedback elements so "the corpus" is visually consistent across all diagrams); teal `#4A8B8C` tertiary.
- **Type:** serif (Georgia-like) for titles, clean sans-serif for labels. Labels must be short — these render at ~800px wide in a blog column, so every word has to survive shrinking.
- **Tone:** flat, calm, editorial. No gradients, no drop shadows, no isometric 3D, no stock-illustration people, no company logos (name sources in plain text instead).
- **Format:** landscape 3:2 or 4:3 unless noted. Leave comfortable margins.

---

## Diagram 1 — "The Soundings stack" (hero image)

**Purpose:** The one image that explains the whole system. A question travels down through the layers to the data; a capture channel runs up the side, turning every question into the public corpus that feeds back to data publishers. This is the diagram of the post's core argument: the layers exist to connect questions to data, and the questions themselves become data.

**Content, top to bottom (main stack):**
1. **People & assistants** — "A charity worker · a funder · a researcher · an AI assistant" with a speech bubble: *"What's happening with child poverty in Stockton?"*
2. **Question layer** — a band holding the ask interface and the tool names as small pills: `find_place`, `get_place_profile`, `get_indicators`, `compare_places`, `get_trend`, `find_organisations_in_place`. Sub-label: "question-shaped tools (MCP)".
3. **Orchestration layer** — three side-by-side boxes: "Geography spine (postcode → neighbourhood → local authority)", "Indicator catalogue (what exists, where, with what caveats)", "Source adapters + cache".
4. **Sources layer** — a row of plain-text source names: ONS · DWP · NHS/OHID · DfE · MHCLG · police.uk · Charity Commission · 360Giving. Sub-label: "UK open data, scattered across departments".

**Side channel (right-hand edge, in warm gold):** a slim vertical track labelled "every consented question" flowing from the Question layer into a box **"Public questions corpus"** (monthly release, CC BY), with a dashed gold arrow returning up/leftwards to the Sources layer labelled **"gap signals → what data is missing"**.

**Down the stack:** one sage-green arrow following the question down; a returning arrow labelled "answer, with sources attached".

**Prompt for Claude design:**

> Create a flat editorial architecture diagram titled "The Soundings stack", landscape 3:2. Warm cream background #F5F0E8, white rounded-corner boxes with #E5DDD0 borders, navy #2D3E50 headings, #5A6B7B labels, sage green #5B8A72 arrows/accents, warm gold #C9A84C reserved for the corpus elements. Serif title, sans-serif labels. No gradients, shadows, 3D, logos, or people illustrations.
>
> Main stack, four horizontal layers top to bottom: (1) "People & assistants" — small text "a charity worker · a funder · a researcher · an AI assistant" plus a speech bubble reading "What's happening with child poverty in Stockton?"; (2) "Question layer — question-shaped tools (MCP)" containing six small pill labels: find_place, get_place_profile, get_indicators, compare_places, get_trend, find_organisations_in_place; (3) "Orchestration" containing three boxes: "Geography spine — postcode → neighbourhood → local authority", "Indicator catalogue — what exists, where, with what caveats", "Adapters + cache"; (4) "UK open data — scattered across departments" listing in plain text: ONS, DWP, NHS/OHID, DfE, MHCLG, police.uk, Charity Commission, 360Giving.
>
> A sage green arrow runs down the stack (the question travelling to the data) and a paired arrow returns upward labelled "answer, with sources attached". On the right edge, a slim warm-gold vertical channel labelled "every consented question" flows from the Question layer into a gold-accented box "Public questions corpus — monthly, CC BY", with a dashed gold arrow curving back to the sources layer labelled "gap signals: what data is missing". Keep all labels short and legible at 800px wide.

---

## Diagram 2 — "One ask, end to end" (the harnessed AI loop)

**Purpose:** Shows how a single natural-language question becomes an answer, with the guardrails made visible. The message: the model composes, the database renders; the AI is on a short lead.

**Content, left to right:**
1. **Question** — "Is Hartlepool getting healthier?"
2. **Claude tool-use loop** — a circular/looping motif: "plan → call tool → read result → repeat". Attached small tags: "max 12 rounds", "45s budget".
3. **Tools called** (stacked small boxes the loop points at): `find_place`, `get_trend`, `compare_places`, `detect_insights` — with a footnote tag on detect_insights: "pure SQL, deterministic — the model narrates signals it didn't invent".
4. **compose_answer** — a gate/checkpoint box: "typed blocks only · max 20 blocks · max 6 visuals · schema-validated".
5. **Rendered answer** — a mini answer mock: a text block, an indicator card, a small trend chart, an insight callout, and a "Sources" footer. Annotation: "numbers filled in by the server from the data — not written by the model".

**Underneath, full width:** a thin bar labelled "every value carries: source · licence · retrieved-at · live/cached/stale".

**Prompt for Claude design:**

> Create a flat editorial process diagram titled "One ask, end to end", landscape 3:2. Warm cream background #F5F0E8, white rounded boxes with #E5DDD0 borders, navy #2D3E50 headings, #5A6B7B text, sage green #5B8A72 arrows and accents, teal #4A8B8C for small guardrail tags. Serif title, sans-serif labels. Flat, no gradients or 3D, no logos.
>
> Left to right: (1) a speech bubble "Is Hartlepool getting healthier?"; (2) a circular loop labelled "Claude tool-use loop: plan → call tool → read result → repeat", with two small teal tags attached: "max 12 rounds" and "45s budget"; (3) a stack of four small tool boxes the loop points to: find_place, get_trend, compare_places, detect_insights — the last one annotated "pure SQL, deterministic"; (4) a gate-style checkpoint box "compose_answer — typed blocks only · max 20 blocks · max 6 visuals · schema-validated"; (5) a mock answer card showing a paragraph block, an indicator stat card, a tiny line chart, a highlighted callout, and a "Sources" footer — annotated "numbers filled in by the server from the data, not written by the model". Along the bottom, a thin full-width bar: "every value carries: source · licence · retrieved-at · live/cached/stale". Short labels, legible at 800px wide.

---

## Diagram 3 — "From question to commons" (capture & consent pipeline)

**Purpose:** Shows the journey of a question into the public corpus, with consent as the gate at the front and sanitisation as the filter in the middle. The message: capture is careful, consented, and reviewable — and the output is a public asset.

**Content, left to right:**
1. **A question is asked** — small spark/dot.
2. **Consent gate** — a three-position switch: "Full — question + context", "Minimal — structure only (default)", "None — nothing captured". The "None" path exits the diagram with a small "still works, nothing stored" label.
3. **Raw store** — a locked box: "raw record · locked down · 30 days · then deleted". Tag: "replayable if rules improve".
4. **Sanitiser** — a filter shape listing rules as short lines: "strip unit postcodes · remove personal names · redact small charities (<£100k) · coarsen fine geography". A branch below to a small human icon-free box: "2+ rules fired? → human review".
5. **Question record** — clean card: "the publishable record".
6. **Monthly release** (warm gold, matching Diagram 1): "corpus-YYYY-MM · CSV + JSONL · CC BY 4.0 · checksums + rules version".
7. **Who uses it** — three short arrows out: "researchers", "funders", "data publishers ← gap signals".

**Prompt for Claude design:**

> Create a flat editorial pipeline diagram titled "From question to commons", landscape 3:2 or wider. Warm cream background #F5F0E8, white rounded boxes with #E5DDD0 borders, navy #2D3E50 headings, #5A6B7B text, sage green #5B8A72 arrows, warm gold #C9A84C reserved for the final published-corpus elements. Serif title, sans-serif labels. Flat, calm, no gradients, no 3D, no logos, no illustrated people.
>
> Left to right: (1) a small dot labelled "a question is asked"; (2) a three-position consent switch: "Full — question + context", "Minimal — structure only (default)", "None — nothing captured", with the None path exiting downward labelled "still works, nothing stored"; (3) a box with a small padlock: "Raw record — locked down, 30 days, then deleted", tagged "replayable if rules improve"; (4) a funnel/filter labelled "Sanitiser" listing four short rules: "strip unit postcodes", "remove personal names", "redact small charities (<£100k)", "coarsen fine geography", with a branch below: "2+ rules fired? → human review"; (5) a clean card "Question record — the publishable record"; (6) a gold-accented box "Monthly release — CSV + JSONL · CC BY 4.0 · checksums + rules version"; (7) three short outgoing arrows labelled "researchers", "funders", "data publishers ← gap signals". Keep labels short and legible at 800px wide.

---

## Diagram 4 (optional) — "Two speeds of data, honestly labelled"

**Purpose:** Small supporting diagram for the adapters/freshness section. Only worth commissioning if the post feels under-illustrated in the middle; the concept also survives as prose.

**Content:** Two lanes into one "Soundings answer" box. Top lane (loader): "bulk downloads on a schedule — Census, IMD, charity register → stored locally → fast". Bottom lane (passthrough): "live APIs on demand — health, benefits → cached with TTL → fresh". On the right, three status badges styled like small pills: `live` (sage), `cached` (teal), `stale` (gold outline) with the caption: "stale data is allowed; hidden degradation is not."

**Prompt for Claude design:**

> Create a small flat diagram titled "Two speeds of data, honestly labelled", landscape 16:9. Same style system: cream #F5F0E8 background, white rounded boxes with #E5DDD0 borders, navy #2D3E50 headings, #5A6B7B text, sage #5B8A72 / teal #4A8B8C / gold #C9A84C accents, serif title, sans-serif labels, flat and calm.
>
> Two horizontal lanes converging into a box on the right labelled "the answer". Top lane "Loader — bulk, on a schedule": "Census · IMD · charity register → stored locally → fast". Bottom lane "Passthrough — live, on demand": "health · benefits → cached with a time-to-live → fresh". At the convergence point, three small status pills: "live" in sage green, "cached" in teal, "stale" in gold outline. Caption beneath in italic: "stale data is allowed; hidden degradation is not." Minimal labels, legible at 800px wide.

---

## Diagram 5 (optional) — header illustration, the sounding line

**Purpose:** A decorative opener rather than an explainer — the nautical metaphor as an image. A weighted sounding line dropping from a small boat through layered water, where the layers are subtly labelled as data strata.

**Prompt for Claude design:**

> Create a calm, flat editorial header illustration, wide banner ratio around 21:9. Warm cream sky #F5F0E8, a simple small boat in navy #2D3E50 on a flat water line, and a weighted sounding line dropping vertically from the boat down through four subtly differentiated horizontal bands of water in muted sage #5B8A72 and teal #4A8B8C tones, deepening toward navy. Each band carries one faint, small, elegant text label: "questions", "tools", "sources", "corpus" — the deepest band's label in warm gold #C9A84C. The plumb weight at the end of the line just touches the deepest band. No people, no logos, no text other than the four labels. Flat shapes, no gradients or texture, generous negative space so a blog title could sit over the sky if needed.

---

## Handoff notes

- Commission Diagrams 1–3 first; they map 1:1 to the `[IMAGE n]` placeholders in the draft. 4 and 5 are nice-to-haves.
- Ask for SVG or high-res PNG at 1600px+ wide; they'll display at ~800px.
- The gold-means-corpus convention across diagrams 1, 3 and 4 is deliberate — keep it if any prompt gets edited.
- Alt text suggestions for the post: 1 — "Layer diagram: questions from people and AI assistants pass through question-shaped tools and an orchestration layer to UK open data sources, while a side channel captures consented questions into a public corpus that feeds gap signals back to publishers." 2 — "Process diagram: a question enters a bounded Claude tool-use loop, which calls Soundings tools and must finish through a validated compose_answer gate before the server renders the final answer with sources." 3 — "Pipeline diagram: a question passes a consent gate, is stored raw for 30 days, filtered by a sanitisation pipeline with human review, and published monthly as an open-licensed corpus."

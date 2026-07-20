# Building Soundings: a question-shaped layer over UK open data

> Another blog on the ins and outs of something I've built, what it's all about, and why it might be a useful tool and/or concept. This time: Soundings — an MCP server that wraps UK open data behind question-shaped tools, an AI interface that's deliberately kept on a short lead, and a public corpus of every question people ask it.

This is another in a series of blogs exploring things I've built, lifting the lid on both the technical and conceptual ideas behind them. If you've read [Building Open Recommendations](https://tomcw.xyz/building-open-recommendations/) or [Building llms.txt for the social sector](https://tomcw.xyz/building-llms-txt-for-the-social-sector/), you'll know the drill: practical, a bit technical, no hype.

This one is the biggest thing I've built so far, and it pulls together threads I've been tugging at for a while. I've written before about [why the biggest barrier to data isn't really data at all](https://tomcw.xyz/bridging-the-data-gap-a-semantic-translation-layer-for-uk-poverty-data/) — that the gap is in the connection between data and need, not in the data itself. And I've written about [why starting with questions changes everything](https://tomcw.xyz/the-power-of-a-question-centred-approach-to-data/). Soundings is what happens when you take both of those ideas seriously and actually build the thing.

## What is Soundings?

A "sounding" is the old nautical practice of dropping a weighted line over the side of a ship to measure the depth of the water. You can't see the bottom, so you take a measurement. That's the idea: taking the measure of local need.

In practical terms, Soundings is two things:

* **An orchestration layer.** A single server that wraps a curated set of UK open data sources — ONS Census, the Index of Multiple Deprivation, DWP benefits data, NHS health indicators, DfE education data, police.uk crime data, the Charity Commission register, 360Giving grants data, and more — behind a small set of question-shaped tools. You ask about a place; it works out which government department holds which dataset, fetches the numbers, and hands them back with full source citations.
* **A capture layer.** Every question asked, with consent, becomes a structured record in a public corpus. Not just for transparency — the questions themselves are the most valuable dataset the sector doesn't have. More on that later.

If someone at a charity asks "what's happening with child poverty in Stockton?", the answer exists. It's just spread across four government departments, three different websites, two APIs that need registration keys, and a set of geography codes that only make sense if you already know what an LSOA is. Soundings' job is to make that one question, with one answer, with the receipts attached.

## What is MCP? (key term, sorry)

Soundings is built as an MCP server. MCP — the [Model Context Protocol](https://modelcontextprotocol.io/) — is an open standard for connecting AI systems to external tools and data. The easiest way to think about it is as a standard socket: any AI assistant that speaks MCP (Claude, and increasingly most of the others) can plug into any MCP server and use its tools, without anyone building a bespoke integration.

This matters because it means Soundings isn't an app you have to visit. It's infrastructure other things plug into. You can use it from the Soundings website, yes — but you can also add it to Claude and ask questions about places in the middle of whatever else you're doing. A funder's AI assistant can call it while assessing a bid. The interface layer is deliberately not the point.

If you read the llms.txt post, you'll recognise the theme: I keep building the boring plumbing rather than the shiny chat interface. This is that, again, at a bigger scale.

## Question-shaped tools

Here's the design decision the whole thing hangs off. Most data services expose *datasets*: "here is table QS103EW, good luck." Soundings exposes *questions*. The core tools are:

* `find_place` — "where is this?" Turns "Stockton", or a postcode, into a canonical place.
* `get_place_profile` — "what's this place like?" A baseline across population, deprivation, economy, health, education, housing, crime.
* `get_indicators` — "what's the number for X here?"
* `compare_places` — "how does it compare?" With percentiles against similar places, because a raw number without context is mostly noise.
* `get_trend` — "is it getting better or worse?" Time series, including honest notes about breaks in the data where methodology changed.
* `find_organisations_in_place` — "who's working on this here?" Charities, their classifications, and the grants flowing in.

That's the question-centred approach made concrete. The tool surface *is* a set of questions, and behind each one the server does the unglamorous work of knowing that child poverty lives with DWP, school attainment with DfE, and life expectancy with the Office for Health Improvement and Disparities. The user's framing goes in; the departmental alphabet soup stays hidden — exactly the "semantic translation layer" I sketched in the [data gap post](https://tomcw.xyz/bridging-the-data-gap-a-semantic-translation-layer-for-uk-poverty-data/), except pointed at answering the question rather than just finding the dataset.

**[IMAGE 1 — "The Soundings stack": the layer diagram, see diagram briefs]**

## How it actually works

Let me break down the layers, bottom to top.

### The geography spine

Everything spatial in the UK hangs off a system of statistical geographies — LSOAs (Lower Super Output Areas, neighbourhoods of around 1,500 people), local authorities, wards, constituencies, regions. Every place in Soundings normalises to one of these, and a geography service handles the lookups: postcode to neighbourhood, neighbourhood to local authority, and the history of boundary changes (councils merge and split more often than you'd think).

One rule here that I'll come back to: **if the geography lookup fails, the whole request fails.** Soundings will not quietly guess which place you meant. Wrong numbers about the right place are bad; right numbers about the wrong place are worse.

### The adapters (two speeds of data)

Each upstream source gets its own adapter, and they come in two flavours — a genuine quality/speed trade-off:

* **Loader mode** for bulk, slow-changing sources. The Census, the IMD, the Charity Commission register get downloaded on a schedule and stored locally. Fast to query, slightly behind the source.
* **Passthrough mode** for live APIs. Health indicators, benefits data get fetched on demand and cached with a time-to-live. Fresher, but slower and dependent on someone else's server being up.

Every value returned carries a `cache_status`: `live`, `cached`, or `stale`. If an upstream API is down and Soundings serves you yesterday's cached number instead, it *tells you*. The rule I wrote into the design doc: stale data is allowed; hidden degradation is not.

### The catalogue

Sitting across the adapters is a versioned catalogue of indicators — a machine-readable file that says, for every measure, what it is, what unit it's in, whether higher is better or worse, which source it comes from, what geographies it's available at, and what the caveats are ("not directly comparable across UK nations", that sort of thing). The catalogue is the contract. And it encodes another refusal: if an indicator only exists at local authority level and you ask for it at neighbourhood level, you get an explicit "not available at this level" error. The server refuses rather than silently approximates. That's a sentence that appears, verbatim, in the spec, and it might be my favourite sentence in the whole project.

### The ask interface (finally, the AI bit)

On top of the tools sits a natural-language interface: you type a question, and Claude runs what's called a tool-use loop — it reads your question, decides which of the tools to call, looks at the results, maybe calls a few more, and then composes an answer. This is the same pattern as the RAG approach I described in the Open Recommendations post (the AI can only draw on what it's been given), but with live tools instead of a document store.

And this is where I want to slow down, because *how* the AI is harnessed is the most transferable part of this whole post.

## Keeping the AI on a short lead

I've said before that the most consistent thing about LLMs is that they're inconsistent. If you're going to put one between the public and official statistics, you need more than good intentions. Here's the harness:

**The model composes; the database renders.** Claude doesn't write the answer as free text. It has to finish by calling a tool called `compose_answer`, handing over a strictly-validated list of typed blocks: a text block, an indicator card, a trend chart, a comparison chart, an insight callout. The cards and charts don't contain numbers the model wrote — they contain *references* (this indicator, this place), and the server fills in the values straight from the data it fetched. The model chooses what to show; it doesn't get to freehand the figures.

**The insights are deterministic.** There's a tool called `detect_insights` that finds the statistically notable things about a place — is it in the bottom decile of similar places for something? Diverging sharply from the median? Has a trend just reversed? Crucially, this is pure SQL. No AI involved. The same place and the same data produce the same signals every single time. Claude's job is to *narrate* over signals it didn't invent, which is the bit LLMs are genuinely good at.

**Hard limits everywhere.** The loop gets a maximum number of tool calls before it's cut off. There's a timeout. An answer can't exceed twenty blocks, of which at most six can be visual — because an AI that can generate unlimited charts will, and a wall of charts is its own kind of dishonesty.

**A scope fence.** Ask it about the weather, the news, or for an opinion, and the system prompt instructs it to say, in one short block, that Soundings can't help with that — no tool calls, no improvising. Knowing what you can't answer is a feature.

**Citations are structural, not optional.** Every value that flows through the system carries a source reference: publisher, dataset, licence, when it was retrieved, and that cache status from earlier. The sources footer on every answer isn't the model being polite; it's assembled by the server from what was actually fetched.

The pattern underneath all of this: use the AI for what it's uniquely good at (understanding the question, choosing the tools, explaining the results in plain language) and use boring deterministic code for everything where being wrong has a cost. Schema validation, controlled vocabularies, strict structures — same principles as Open Recommendations, with the stakes turned up.

**[IMAGE 2 — "One ask, end to end": the ask loop diagram, see diagram briefs]**

One honest confession while I'm here. Regular readers will know I bang on about provider-agnostic AI. The ask loop currently uses the Anthropic SDK directly — the model is a config setting, but the plumbing is Claude-shaped. A pragmatic exception rather than a change of heart: the tool handlers are all in-process and cleanly separated, so swapping the loop's brain out later is contained. But I'd be breaking my own rule not to flag that I'm breaking my own rule.

## The corpus: questions as a public asset

Now the part I think matters most, and the reason "capture" is in the architecture from day one rather than bolted on.

Every tool call — every sounding — becomes a structured record: what was asked, about where, what tools answered it, which sources were used, and whether it worked. With consent, and with care:

* **Three consent levels.** *Full* captures your actual question and optional context about who's asking (a charity? a funder? a resident?). *Minimal* — the default — captures only the structured skeleton: tool, place, indicators. *None* captures nothing at all, and you can still use everything.
* **A sanitisation pipeline** runs before anything becomes publishable: unit-level postcodes stripped, personal names removed with named entity recognition (an automated technique for spotting names in text — with the sensible caveat that it's imperfect, which is why there's more than one layer here), names of small charities redacted (under £100k income, you're potentially identifiable in context), and geographic references in free text coarsened to areas of a few thousand people or more. If more than one rule fires on a single record, it doesn't get auto-published — it goes to a human review queue.
* **The raw pre-sanitisation records** live for 30 days in a locked-down store — long enough to debug and to re-run the sanitiser if the rules improve, then gone.
* **Monthly publication.** The clean corpus goes out as downloadable data files under an open licence (CC BY 4.0), with a manifest of checksums and the exact versions of the catalogue and sanitisation rules that were live — so anyone can verify what they've downloaded and understand exactly how it was processed.

Why go to all this trouble? Because of the argument in the data gap post. Right now, thousands of organisations ask essentially the same questions about their places, separately, invisibly, and the knowledge of what people actually need to know exists nowhere. A public corpus of questions makes demand visible. Which questions come up everywhere? Which ones couldn't be answered because the data doesn't exist at the right level, or at all? The system logs those misses too — every answer includes the questions it *couldn't* answer — and over time that becomes an evidence base for data publishers: here is what people are trying to find out, and here is exactly where you're failing them. The gap between data supply and data demand, measured instead of guessed at.

**[IMAGE 3 — "From question to commons": the capture pipeline diagram, see diagram briefs]**

## Decisions and trade-offs

A few choices worth lifting the lid on, because the reasoning is more useful than the choices themselves.

**It runs on a Mac mini.** The whole thing — database, server, loaders, website — runs on a single small machine in the North East of England, reaching the internet through a tunnel so nothing needs a fancy hosting contract. This is deliberate. Infrastructure for the social sector should be cheap enough to run on hardware you already own, and designing for one machine forces honest decisions about complexity.

**Postgres for everything.** No vector database, no Redis, no message queue. One boring, reliable database holds the geography, the cached data, and the corpus. Every extra moving part is something else to break, back up, and explain. I'll add a vector store for "find similar questions" when full-text search actually proves insufficient, not before.

**Pre-warming instead of making you wait.** Some numbers are expensive to compute — counting active charities in a place means crunching a large register. A background process pre-computes these on a schedule so users get warm-cache answers, trading a bit of staleness (labelled, as always) for a lot of speed.

**Build things when they're needed, not when they're conceivable.** Charts didn't get built until there was time-series data worth plotting. The decision record for that contains a line I stand by: a chart of a single value is just a number with extra DOM.

**Recorded API responses for testing.** Every adapter is tested against recorded copies of real upstream responses, so the test suite runs fast and offline, with a separate nightly suite hitting the real APIs to catch the inevitable day a government department changes their response format without telling anyone. (There will be such a day. There always is.)

## Limitations (there are plenty)

* **Coverage is England-heavy.** Many sources are England-only or England-first, so Scotland, Wales and Northern Ireland are unevenly covered. The catalogue documents the gaps rather than papering over them, but documented unevenness is still unevenness.
* **The corpus needs volume to be valuable.** A public dataset of questions is only as interesting as the questions in it. Early on, that's a small number of records and a lot of infrastructure. This is a long game.
* **The AI layer costs real money.** Every natural-language ask is API calls to a frontier model. Caching and hard limits keep it sane, but "free for everyone forever" and "no funding" are in tension, and I haven't resolved it — the llms.txt post's open-source-plus-paid experiment is one possible shape.
* **Sanitisation will never be perfect.** Automated redaction plus thresholds plus human review is a serious attempt, not a guarantee. The design assumes rules will improve, which is why raw records are replayable against new rules for their 30-day window.
* **One machine is one machine.** If the Mac mini goes down, Soundings goes down. Fine for this stage; not a national service. Yet.
* **A question-shaped surface can't answer every question.** Some things people ask don't map onto any tool. But those misses get captured, and the misses are the roadmap. That's not spin — it's the actual mechanism by which the tool surface grows.

## What I've learned

**The 80/20 split, again, but more so.** In Open Recommendations I reckoned the AI was about 20% of the system. Here it's less. The geography spine, the adapters, the caching, the sanitisation pipeline, the migrations, the tests — the AI-touching code is a thin layer on a large pile of deliberately boring engineering. The AI is what makes it feel effortless; the engineering is what makes it trustworthy.

**Honesty is a feature you have to build.** `cache_status`, caveats on every indicator, breaks-in-series notes, "refuse rather than silently approximate", questions-we-couldn't-answer. None of that appears by default in any system — silence is always cheaper in the short run. Every one of those honesty features had to be designed in, and collectively they're the product.

**Harness beats hope.** Typed blocks, terminal tools, deterministic insights, iteration caps, structural citations. The lesson isn't "don't trust the AI"; it's that trust is something you engineer. Give the model a narrow, well-shaped channel and it's genuinely excellent. Give it an open mic and you're gambling with someone else's understanding of their community.

**Questions are infrastructure.** The deepest idea here isn't any of the plumbing. It's that the questions people ask are a dataset — arguably *the* dataset — and nobody has been collecting it. If Soundings works, the corpus ends up mattering more than the server.

## Try it, steal it, tell me I'm wrong

The whole thing is open: the server code is open source (AGPL), the data schemas are public domain (CC0), the specs are CC BY, and the corpus is downloadable from the site. If you're technical, you can run the entire stack yourself with Docker and a spare afternoon.

And if any of this sparks something — you work with places data, you fund things and wish you could see the demand side, you think the corpus idea is naive, you want to plug Soundings into something you're building — give me a shout on tom@good-ship.co.uk or on the [linky](https://www.linkedin.com/in/tomcampbellwatson/).

The data exists. The questions exist. Soundings is a bet that the most useful thing to build is the connection between them — and a public record of every time we make it.

# Ask Interface — Browser Smoke Runbook

**Prerequisites:**
- Docker stack up (`make up`)
- `ANTHROPIC_API_KEY` set in `.env`
- Server on :8001, UI on :4321

## Steps

### 1. Homepage ask (open mode)

1. Go to `http://localhost:4321/`
2. Type "What's the population of Stockton-on-Tees?" in the AskBox
3. Click "Ask"
4. **Expected:** navigates to `/ask?q=…&mode=open`
5. **Expected:** status messages appear ("Calling find_place…", etc.)
6. **Expected:** at least one text block renders with markdown
7. **Expected:** sources footer appears after done

### 2. Place page ask (summary mode)

1. Go to `http://localhost:4321/place/ltla24:E06000004`
2. Click "Summary" chip in the AskBox
3. **Expected:** navigates to `/ask?q=Summarise…&place_id=ltla24:E06000004&mode=summary`
4. **Expected:** answer includes indicator cards + narrative text
5. **Expected:** at least 3 blocks total

### 3. Compare mode

1. Go to `http://localhost:4321/place/ltla24:E06000004`
2. Click "Compare" chip
3. **Expected:** answer includes at least one compare-chart block
4. **Expected:** narrative uses percentile framing

### 4. Insight mode

1. Go to `http://localhost:4321/place/ltla24:E06000004`
2. Click "Surprise me" chip
3. **Expected:** answer includes at least one insight-callout block
4. **Expected:** callouts are ordered by severity (extreme first)

### 5. Out-of-scope question

1. Go to `http://localhost:4321/`
2. Type "What's the weather in Stockton?"
3. **Expected:** single text block explaining Soundings can't help with weather
4. **Expected:** ~1-2s response, no tool calls

### 6. Error handling

1. Stop the server (`docker stop soundings-server`)
2. Type a query and submit
3. **Expected:** error message with retry link
4. Restart server and retry — should work

## Gate

All 6 steps must pass before tagging.

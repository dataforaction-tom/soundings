# Neighbourhood Granularity — Ask Feature Improvements

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make the ask feature work naturally at neighbourhood (LSOA/ward) level, enable comparison between neighbourhoods, and surface sub-area data without requiring the user to know geography type codes.

**Architecture:** Four slices: (1) system prompt + find_place changes so Claude picks the right granularity, (2) a new `get_sub_areas` tool for within-place neighbourhood data, (3) `compare_places` extended to support cross-level comparison (neighbourhood vs neighbourhood, neighbourhood vs LTLA average), (4) UI improvements so the place page and ask results show neighbourhood-level detail.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy + PostGIS, Astro 4, TypeScript, Observable Plot, Leaflet

---

## Current State

**Geography levels in DB:** `lsoa21`, `msoa21`, `ltla24`, `utla24`, `region`, `country`, `ward24`, `westminster_constituency_24` — all seeded with boundaries + hierarchy.

**Indicator availability by level:**
- LTLA: 56/58 indicators (the default)
- LSOA: 17 indicators (population, census, IMD, education)
- MSOA: 11 indicators (population, census)
- Ward: 0 indicators
- Constituency: 2 indicators (DWP benefits)

**What works:**
- `find_place` returns matches across all geography types
- `get_indicators` works at any level if the indicator's `available_at` includes it
- Choropleth `granularity="sub_areas"` shows LSOA deprivation within an LTLA
- `GET /v1/place/{place_id}/children/geometry` returns LSOA-level GeoJSON

**What doesn't work:**
- The system prompt doesn't tell Claude it can work at LSOA level
- No tool returns sub-area data in a single call (Claude would need to call `get_indicators` for each LSOA individually)
- `compare_places` requires same-type peers — can't compare an LSOA against its LTLA average
- No ward-level indicators in the catalogue
- The place page only renders LTLA profiles
- AskBox example questions all assume LTLA-level places

---

## Slice 1: Prompt + find_place improvements *(no new tools)*

### Task 1: Update system prompt for multi-level awareness

**Objective:** Tell Claude that indicators work at multiple geography levels and that "neighbourhood" means LSOA/ward.

**Files:**
- Modify: `server/soundings/ask/prompts.py` — `_SCOPE_DESCRIPTION`

**Step 1: Write failing test**

Add to `server/tests/test_ask_prompts.py`:

```python
def test_prompt_teaches_neighbourhood_resolution():
    """Prompt should explain that 'neighbourhood' means LSOA level."""
    prompt = SystemPromptBuilder().build()
    assert "neighbourhood" in prompt.lower() or "neighborhood" in prompt.lower()
    assert "lsoa" in prompt.lower()
    assert "ward" in prompt.lower()

def test_prompt_explains_geography_levels():
    """Prompt should explain that indicators vary by geography level."""
    prompt = SystemPromptBuilder().build()
    assert "available_at" in prompt or "geography level" in prompt.lower()
    assert "ltla" in prompt.lower()
    assert "lsoa" in prompt.lower()
```

**Step 2: Run test to verify failure**

Run: `cd server && uv run python -m pytest tests/test_ask_prompts.py::test_prompt_teaches_neighbourhood_resolution tests/test_ask_prompts.py::test_prompt_explains_geography_levels -v`
Expected: FAIL

**Step 3: Add guidance to `_SCOPE_DESCRIPTION`**

After the infrastructure amenity paragraph, add:

```
Geography levels: indicators are available at different geography levels.
Most indicators work at ltla24 (Local Authority District) level. Some
indicators are also available at lsoa21 (Lower Layer Super Output Area —
small neighbourhoods of ~1,500 people) and msoa21 (Middle Layer Super
Output Area). When a user says "neighbourhood", "local area", or "small
area", they likely mean LSOA level — use find_place and prefer lsoa21
matches when the question is about neighbourhood-scale analysis. Ward-level
(ward24) data is limited. Check the indicator's available_at before
calling get_indicators at a non-LTLA level — if it's not available, say so.
```

**Step 4: Run test to verify pass**

Run: `cd server && uv run python -m pytest tests/test_ask_prompts.py::test_prompt_teaches_neighbourhood_resolution tests/test_ask_prompts.py::test_prompt_explains_geography_levels -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/soundings/ask/prompts.py server/tests/test_ask_prompts.py
git commit -m "feat: system prompt teaches neighbourhood/LSOA level awareness"
```

---

### Task 2: Guide find_place to prefer granular matches for neighbourhood queries

**Objective:** When the user says "neighbourhood" or "small area", find_place should prefer LSOA/ward matches. This is a prompt-level change, not a code change to the tool — Claude can pass `geography_types: ["lsoa21"]` to find_place.

**Files:**
- Modify: `server/soundings/ask/prompts.py` — `_SCOPE_DESCRIPTION`

**Step 1: Write failing test**

```python
def test_prompt_teaches_geography_types_filter():
    """Prompt should explain that find_place accepts geography_types."""
    prompt = SystemPromptBuilder().build()
    assert "geography_types" in prompt
    assert "lsoa21" in prompt
```

**Step 2: Run test to verify failure**

Run: `cd server && uv run python -m pytest tests/test_ask_prompts.py::test_prompt_teaches_geography_types_filter -v`
Expected: FAIL

**Step 3: Add to the find_place tool description in the prompt**

Update the find_place line in `_SCOPE_DESCRIPTION`:

```
- find_place: resolve a place name or postcode to a canonical geography ID.
  Pass geography_types to filter (e.g. ["lsoa21"] for neighbourhood-scale,
  ["ltla24"] for district-scale). For "neighbourhood" questions, prefer
  lsoa21 matches. Postcodes resolve to all containing levels — use the
  most granular one that has indicators available.
```

**Step 4: Run test to verify pass**

Run: `cd server && uv run python -m pytest tests/test_ask_prompts.py::test_prompt_teaches_geography_types_filter -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/soundings/ask/prompts.py server/tests/test_ask_prompts.py
git commit -m "feat: prompt guides find_place to prefer LSOA for neighbourhood queries"
```

---

### Task 3: Update AskBox example questions for neighbourhoods

**Objective:** Add neighbourhood-level example questions to the AskBox component.

**Files:**
- Modify: `ui/src/components/AskBox.astro` — `examplesWithPlace` and `examplesNoPlace` arrays

**Step 1: Update the example arrays**

```typescript
const examplesWithPlace = [
  "Summarise this place",
  "How does it compare to peers?",
  "What are the most deprived neighbourhoods here?",
  "Where are the food banks?",
];

const examplesNoPlace = [
  "Summarise Stockton-on-Tees",
  "How does Sheffield compare to peers?",
  "Most deprived neighbourhoods in Middlesbrough",
  "Where are the food banks in Leeds?",
];
```

**Step 2: Verify UI tests still pass**

Run: `cd ui && npx vitest run`
Expected: PASS (108 tests)

**Step 3: Commit**

```bash
git add ui/src/components/AskBox.astro
git commit -m "feat: add neighbourhood-level example questions to AskBox"
```

---

## Slice 2: `get_sub_areas` tool *(new tool — within-place neighbourhood data)*

### Task 4: Create `get_sub_areas` tool — input/output models + skeleton

**Objective:** A new ask tool that returns sub-area (LSOA) indicator values within a parent place in a single call, instead of Claude calling `get_indicators` for each LSOA individually.

**Files:**
- Create: `server/soundings/tools/get_sub_areas.py`
- Test: `server/tests/test_get_sub_areas.py`

**Step 1: Write failing test**

```python
"""Tests for the get_sub_areas tool."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from soundings.tools.get_sub_areas import (
    GetSubAreasInput,
    GetSubAreasOutput,
    SubAreaValue,
    tool_spec,
)


def test_tool_spec_has_correct_name():
    spec = tool_spec()
    assert spec["name"] == "get_sub_areas"


def test_input_model_requires_place_id_and_indicator():
    model = GetSubAreasInput(place_id="ltla24:E06000004", indicator_key="deprivation.imd.score")
    assert model.place_id == "ltla24:E06000004"
    assert model.indicator_key == "deprivation.imd.score"
    assert model.child_type == "lsoa21"  # default


def test_output_model_has_sub_areas_list():
    out = GetSubAreasOutput(
        parent_place_id="ltla24:E06000004",
        indicator_key="deprivation.imd.score",
        child_type="lsoa21",
        sub_areas=[
            SubAreaValue(place_id="lsoa21:E01001234", name="Stockton 001A", value=32.5, percentile=85.0),
        ],
        parent_value=22.0,
        parent_percentile=55.0,
        period="2025",
    )
    assert len(out.sub_areas) == 1
    assert out.sub_areas[0].value == 32.5
```

**Step 2: Run test to verify failure**

Run: `cd server && uv run python -m pytest tests/test_get_sub_areas.py -v`
Expected: FAIL — module not found

**Step 3: Implement the tool skeleton**

```python
"""get_sub_areas tool — sub-area indicator values within a parent place.

Returns LSOA-level (or other child-type) values for a single indicator
within a parent place (e.g. all LSOA deprivation scores within an LTLA).
Includes the parent's own value and percentile for context. This is the
single-call equivalent of calling get_indicators for every child — Claude
uses it to answer "what are the most deprived neighbourhoods in X?"
"""

from typing import Any

from pydantic import BaseModel, Field

from soundings.contracts.source_ref import SourceRef


class SubAreaValue(BaseModel):
    place_id: str
    name: str
    value: float | None = None
    percentile: float | None = None  # within parent's peer universe


class GetSubAreasInput(BaseModel):
    place_id: str  # the parent place (e.g. ltla24:E06000004)
    indicator_key: str
    child_type: str = "lsoa21"  # child geography type
    period: str | None = None
    limit: int = 50  # cap to avoid huge responses
    sort_by: str = "value_desc"  # "value_desc", "value_asc", "name"


class GetSubAreasOutput(BaseModel):
    parent_place_id: str
    indicator_key: str
    child_type: str
    sub_areas: list[SubAreaValue] = Field(default_factory=list)
    parent_value: float | None = None
    parent_percentile: float | None = None
    period: str = ""
    sources: list[SourceRef] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


TOOL_NAME = "get_sub_areas"
TOOL_DESCRIPTION = (
    "Get sub-area (neighbourhood-level) indicator values for all children "
    "of a parent place. Default child_type is 'lsoa21' (LSOA — neighbourhoods "
    "of ~1,500 people). Returns each child's value, name, and percentile "
    "within the parent's peer universe, plus the parent's own value for "
    "context. Use this to answer 'what are the most deprived neighbourhoods "
    "in X?' or 'show me neighbourhood-level [indicator] for X'."
)


def tool_spec() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": GetSubAreasInput.model_json_schema(),
        "output_schema": GetSubAreasOutput.model_json_schema(),
    }
```

**Step 4: Run test to verify pass**

Run: `cd server && uv run python -m pytest tests/test_get_sub_areas.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add server/soundings/tools/get_sub_areas.py server/tests/test_get_sub_areas.py
git commit -m "feat: add get_sub_areas tool models and skeleton"
```

---

### Task 5: Implement `get_sub_areas` — query logic

**Objective:** Query PostGIS hierarchy + data.indicator_value to return sub-area values for a parent place.

**Files:**
- Modify: `server/soundings/tools/get_sub_areas.py` — add `get_sub_areas()` async function
- Test: `server/tests/test_get_sub_areas.py`

**Step 1: Write failing integration test**

```python
async def test_get_sub_areas_returns_lsoa_values_for_ltla():
    """Integration test against the test DB with seeded Stockton LSOAs."""
    from soundings.app import app
    from soundings.tools.get_sub_areas import get_sub_areas, GetSubAreasInput

    async with app.router.lifespan_context(app):
        result = await get_sub_areas(
            GetSubAreasInput(
                place_id="ltla24:E06000004",
                indicator_key="deprivation.imd.score",
            ),
            orchestrator=app.state.orchestrator,
            engine=app.state.engine,
        )
    assert result.parent_place_id == "ltla24:E06000004"
    assert len(result.sub_areas) > 0
    assert all(s.place_id.startswith("lsoa21:") for s in result.sub_areas)
    # Sorted by value descending (most deprived first)
    values = [s.value for s in result.sub_areas if s.value is not None]
    assert values == sorted(values, reverse=True)
```

**Step 2: Run test to verify failure**

Run: `cd server && uv run python -m pytest tests/test_get_sub_areas.py::test_get_sub_areas_returns_lsoa_values_for_ltla -v`
Expected: FAIL — function not implemented

**Step 3: Implement the query function**

```python
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

async def get_sub_areas(
    input: GetSubAreasInput,
    orchestrator: Any,  # IndicatorOrchestrator
    engine: AsyncEngine,
) -> GetSubAreasOutput:
    # 1. Get child place IDs via hierarchy
    async with engine.connect() as conn:
        child_rows = (
            await conn.execute(
                text("""
                    SELECT p.id, p.name
                    FROM geography.place_hierarchy ph
                    JOIN geography.place p ON p.id = ph.child_id
                    WHERE ph.parent_id = :parent_id
                      AND p.type = :child_type
                    ORDER BY p.name
                """),
                {"parent_id": input.place_id, "child_type": input.child_type},
            )
        ).all()

    if not child_rows:
        return GetSubAreasOutput(
            parent_place_id=input.place_id,
            indicator_key=input.indicator_key,
            child_type=input.child_type,
            caveats=[f"No {input.child_type} children found for {input.place_id}"],
        )

    # 2. Fetch indicator values for all children in one batched query
    child_ids = [r.id for r in child_rows]
    async with engine.connect() as conn:
        value_rows = (
            await conn.execute(
                text("""
                    SELECT DISTINCT ON (iv.place_id)
                        iv.place_id, iv.value, iv.period
                    FROM data.indicator_value iv
                    WHERE iv.place_id = ANY(:child_ids)
                      AND iv.indicator_key = :indicator_key
                      AND (:period IS NULL OR iv.period = :period)
                    ORDER BY iv.place_id, iv.period DESC
                """),
                {
                    "child_ids": child_ids,
                    "indicator_key": input.indicator_key,
                    "period": input.period,
                },
            )
        ).all()

    value_map = {r.place_id: (r.value, r.period) for r in value_rows}

    # 3. Fetch parent's value and percentile
    parent_value = None
    parent_percentile = None
    try:
        parent_result = await orchestrator._fetch_one(
            input.indicator_key, input.place_id, input.period
        )
        if parent_result:
            parent_value = parent_result.value
            parent_percentile = parent_result.benchmark_percentile
    except Exception:
        pass  # Parent value is context, not critical

    # 4. Build sub-area list
    sub_areas: list[SubAreaValue] = []
    for row in child_rows:
        val_period = value_map.get(row.id)
        if val_period and val_period[0] is not None:
            sub_areas.append(SubAreaValue(
                place_id=row.id,
                name=row.name,
                value=float(val_period[0]),
                percentile=None,  # could be computed from peer distribution
            ))

    # 5. Sort
    if input.sort_by == "value_desc":
        sub_areas.sort(key=lambda s: s.value or 0, reverse=True)
    elif input.sort_by == "value_asc":
        sub_areas.sort(key=lambda s: s.value or 0)
    else:
        sub_areas.sort(key=lambda s: s.name)

    # 6. Cap and determine period
    sub_areas = sub_areas[: input.limit]
    period_used = ""
    if value_rows:
        period_used = value_rows[0].period or ""

    return GetSubAreasOutput(
        parent_place_id=input.place_id,
        indicator_key=input.indicator_key,
        child_type=input.child_type,
        sub_areas=sub_areas,
        parent_value=parent_value,
        parent_percentile=parent_percentile,
        period=period_used,
    )
```

**Step 4: Run test to verify pass**

Run: `cd server && uv run python -m pytest tests/test_get_sub_areas.py::test_get_sub_areas_returns_lsoa_values_for_ltla -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/soundings/tools/get_sub_areas.py server/tests/test_get_sub_areas.py
git commit -m "feat: implement get_sub_areas query for neighbourhood-level data"
```

---

### Task 6: Register `get_sub_areas` in the dispatcher

**Objective:** Wire the new tool into the ask dispatcher and tool spec list so Claude can call it.

**Files:**
- Modify: `server/soundings/ask/dispatcher.py` — import, spec list, handler map
- Test: `server/tests/test_ask_dispatcher.py`

**Step 1: Write failing test**

```python
async def test_dispatcher_has_get_sub_areas_handler():
    from soundings.ask.dispatcher import ToolDispatcher
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    state = SimpleNamespace(
        geography_service=MagicMock(),
        orchestrator=MagicMock(),
        engine=MagicMock(),
    )
    dispatcher = ToolDispatcher(state)
    assert "get_sub_areas" in dispatcher._handlers
```

**Step 2: Run test to verify failure**

Run: `cd server && uv run python -m pytest tests/test_ask_dispatcher.py::test_dispatcher_has_get_sub_areas_handler -v`
Expected: FAIL

**Step 3: Wire into dispatcher**

In `dispatcher.py`:
1. Import: `from soundings.tools.get_sub_areas import GetSubAreasInput, get_sub_areas, tool_spec as get_sub_areas_spec`
2. Add to `specs` list: `get_sub_areas_spec()`
3. Add handler:

```python
async def _handle_get_sub_areas(self, args: dict[str, Any]) -> dict[str, Any]:
    model = GetSubAreasInput.model_validate(args)
    result = await get_sub_areas(model, self._state.orchestrator, self._state.engine)
    return result.model_dump(mode="json")
```

4. Add to `_handlers`: `"get_sub_areas": self._handle_get_sub_areas,`

**Step 4: Run test to verify pass**

Run: `cd server && uv run python -m pytest tests/test_ask_dispatcher.py::test_dispatcher_has_get_sub_areas_handler -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/soundings/ask/dispatcher.py server/tests/test_ask_dispatcher.py
git commit -m "feat: register get_sub_areas in ask dispatcher"
```

---

### Task 7: Add `get_sub_areas` to system prompt

**Objective:** Tell Claude when to use the new tool and how to present sub-area results.

**Files:**
- Modify: `server/soundings/ask/prompts.py` — `_SCOPE_DESCRIPTION`
- Test: `server/tests/test_ask_prompts.py`

**Step 1: Write failing test**

```python
def test_prompt_mentions_get_sub_areas():
    prompt = SystemPromptBuilder().build()
    assert "get_sub_areas" in prompt
    assert "neighbourhood" in prompt.lower()

def test_prompt_teaches_sub_areas_for_neighbourhood_questions():
    prompt = SystemPromptBuilder().build()
    assert "most deprived neighbourhoods" in prompt.lower()
    assert "sub-area" in prompt.lower() or "sub area" in prompt.lower()
```

**Step 2: Run test to verify failure**

Run: `cd server && uv run python -m pytest tests/test_ask_prompts.py::test_prompt_mentions_get_sub_areas tests/test_ask_prompts.py::test_prompt_teaches_sub_areas_for_neighbourhood_questions -v`
Expected: FAIL

**Step 3: Add tool to prompt**

Add to the tool list in `_SCOPE_DESCRIPTION`:

```
- get_sub_areas: get all sub-area (LSOA/neighbourhood) values for an indicator
  within a parent place. Use for "most deprived neighbourhoods in X" or
  "show me neighbourhood-level [indicator] in X". Returns each child's
  value plus the parent's own value for context. Pair with a sub_areas map
  (granularity="sub_areas") to show the geographic distribution.
```

Also add to the intent inference section:

```
- Neighbourhood questions ("most deprived neighbourhoods in X",
  "show me [indicator] by neighbourhood") → call get_sub_areas for the
  parent place, include a sub_areas choropleth map, and list the most
  extreme sub-areas with their values.
```

**Step 4: Run test to verify pass**

Run: `cd server && uv run python -m pytest tests/test_ask_prompts.py::test_prompt_mentions_get_sub_areas tests/test_ask_prompts.py::test_prompt_teaches_sub_areas_for_neighbourhood_questions -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/soundings/ask/prompts.py server/tests/test_ask_prompts.py
git commit -m "feat: system prompt teaches get_sub_areas for neighbourhood questions"
```

---

## Slice 3: Neighbourhood comparison

### Task 8: Extend `compare_places` to support cross-level comparison

**Objective:** Allow comparing an LSOA against its LTLA average (and other cross-level comparisons) by adding an optional `context_place_id` parameter. The LTLA's value becomes a "context row" in the results.

**Files:**
- Modify: `server/soundings/tools/compare_places.py` — add `context_place_ids` param
- Modify: `server/soundings/orchestration/orchestrator.py` — `_compare_one` to include context places without enforcing same type
- Test: `server/tests/test_compare_places.py` (or create if doesn't exist)

**Step 1: Write failing test**

```python
async def test_compare_places_with_context_ltla():
    """Comparing two LSOAs with their parent LTLA as context."""
    from soundings.tools.compare_places import ComparePlacesInput, compare_places
    from soundings.app import app

    async with app.router.lifespan_context(app):
        result = await compare_places(
            ComparePlacesInput(
                place_ids=["lsoa21:E01001234", "lsoa21:E01001235"],
                indicators=["deprivation.imd.score"],
                context_place_ids=["ltla24:E06000004"],
            ),
            orchestrator=app.state.orchestrator,
        )
    # Should have comparisons for both LSOAs + the LTLA as a context row
    assert len(result.results) >= 2
    # The context LTLA should appear in results with is_context=True
    context_results = [r for r in result.results if getattr(r, "is_context", False)]
    assert len(context_results) >= 1
```

**Step 2: Run test to verify failure**

Run: `cd server && uv run python -m pytest tests/test_compare_places.py::test_compare_places_with_context_ltla -v`
Expected: FAIL

**Step 3: Implement context_place_ids**

Add `context_place_ids: list[str] = Field(default_factory=list)` to `ComparePlacesInput`. In the orchestrator's compare logic, fetch context place values separately (skip level enforcement for context places, since they're for context not ranking).

**Step 4: Run test to verify pass**

Run: `cd server && uv run python -m pytest tests/test_compare_places.py::test_compare_places_with_context_ltla -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/soundings/tools/compare_places.py server/soundings/orchestration/orchestrator.py server/tests/test_compare_places.py
git commit -m "feat: compare_places supports context_place_ids for cross-level comparison"
```

---

### Task 9: Update system prompt for neighbourhood comparison

**Objective:** Tell Claude how to compare neighbourhoods using compare_places with context.

**Files:**
- Modify: `server/soundings/ask/prompts.py`
- Test: `server/tests/test_ask_prompts.py`

**Step 1: Write failing test**

```python
def test_prompt_teaches_neighbourhood_comparison():
    prompt = SystemPromptBuilder().build()
    assert "context_place_ids" in prompt
    assert "neighbourhood" in prompt.lower()
```

**Step 2: Run test to verify failure**

Run: `cd server && uv run python -m pytest tests/test_ask_prompts.py::test_prompt_teaches_neighbourhood_comparison -v`
Expected: FAIL

**Step 3: Add to compare_places tool description in prompt**

```
- compare_places: compare places against peers (percentile, rank, absolute, rate).
  Pass context_place_ids to include parent-level places as context rows
  (e.g. compare two LSOAs with their LTLA as context: place_ids=["lsoa21:A",
  "lsoa21:B"], context_place_ids=["ltla24:X"]). Use for "how do these
  neighbourhoods compare to each other and to the district average?"
```

Also add to intent inference:

```
- Neighbourhood comparison ("how do these neighbourhoods compare",
  "compare LSOAs in X") → call compare_places with the LSOA place_ids
  and the parent LTLA as a context_place_id.
```

**Step 4: Run test to verify pass**

Run: `cd server && uv run python -m pytest tests/test_ask_prompts.py::test_prompt_teaches_neighbourhood_comparison -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/soundings/ask/prompts.py server/tests/test_ask_prompts.py
git commit -m "feat: prompt teaches neighbourhood comparison with context_place_ids"
```

---

## Slice 4: UI — neighbourhood-level rendering

### Task 10: Render sub-area results in the ask answer stream

**Objective:** When `get_sub_areas` returns data, the ask answer should render a sub-area table or list showing each neighbourhood's value, sorted by severity.

**Files:**
- Modify: `ui/src/scripts/ask_page.ts` — add renderer for sub-area data (rendered as a table block from the tool result, or as text if the model includes it in a text block)
- Modify: `server/soundings/ask/blocks.py` — add `SubAreaTableBlock`

**Step 1: Write failing test for the block type**

```python
def test_sub_area_table_block_exists():
    from soundings.ask.blocks import SubAreaTableBlock
    block = SubAreaTableBlock(
        type="sub-area-table",
        parent_place_id="ltla24:E06000004",
        indicator_key="deprivation.imd.score",
        sub_areas=[
            {"place_id": "lsoa21:E01001234", "name": "Stockton 001A", "value": 32.5},
            {"place_id": "lsoa21:E01001235", "name": "Stockton 001B", "value": 28.1},
        ],
        parent_value=22.0,
        period="2025",
    )
    assert block.type == "sub-area-table"
    assert len(block.sub_areas) == 2
```

**Step 2: Run test to verify failure**

Run: `cd server && uv run python -m pytest tests/test_ask_blocks.py::test_sub_area_table_block_exists -v`
Expected: FAIL

**Step 3: Implement SubAreaTableBlock**

In `blocks.py`:

```python
class SubAreaEntry(BaseModel):
    place_id: str
    name: str
    value: float | None = None
    percentile: float | None = None

class SubAreaTableBlock(BaseModel):
    type: Literal["sub-area-table"]
    parent_place_id: str
    indicator_key: str
    sub_areas: list[SubAreaEntry]
    parent_value: float | None = None
    period: str | None = None
    caption: str | None = None
```

Add `"sub-area-table"` to the `AnswerBlock` discriminated union.

**Step 4: Run test to verify pass**

Run: `cd server && uv run python -m pytest tests/test_ask_blocks.py::test_sub_area_table_block_exists -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/soundings/ask/blocks.py server/tests/test_ask_blocks.py
git commit -m "feat: add SubAreaTableBlock for neighbourhood-level results"
```

---

### Task 11: Render sub-area table in the UI

**Objective:** Add a renderer for `sub-area-table` blocks in the ask page.

**Files:**
- Modify: `ui/src/scripts/ask_page.ts` — add `renderSubAreaTable` function
- Test: `ui/tests/answer_stream.test.ts` (if applicable)

**Step 1: Implement the renderer**

In `ask_page.ts`, add a renderer for `block.type === "sub-area-table"` that:
1. Creates a table with columns: Neighbourhood, Value, (optional) Percentile
2. Highlights the parent value as a separate row or footnote
3. Shows the period if present
4. Sorts by value (already sorted by the server)

**Step 2: Verify UI tests pass**

Run: `cd ui && npx vitest run`
Expected: PASS

**Step 3: Commit**

```bash
git add ui/src/scripts/ask_page.ts
git commit -m "feat: render sub-area table blocks in ask answer stream"
```

---

### Task 12: Add sub-area-table to system prompt block guidance

**Objective:** Tell Claude when to use the sub-area-table block.

**Files:**
- Modify: `server/soundings/ask/prompts.py` — `_BLOCK_GUIDANCE`
- Test: `server/tests/test_ask_prompts.py`

**Step 1: Write failing test**

```python
def test_prompt_mentions_sub_area_table():
    prompt = SystemPromptBuilder().build()
    assert "sub-area-table" in prompt
```

**Step 2: Run test to verify failure**

Run: `cd server && uv run python -m pytest tests/test_ask_prompts.py::test_prompt_mentions_sub_area_table -v`
Expected: FAIL

**Step 3: Add to block guidance**

```
- sub-area-table: a table of sub-area (neighbourhood) values within a parent
  place. Use after calling get_sub_areas — the block carries the sub_areas
  data inline. Pair with a sub_areas choropleth map for the geographic view.
  Sort by value (most extreme first) so the user sees the standout
  neighbourhoods without scrolling.
```

**Step 4: Run test to verify pass**

Run: `cd server && uv run python -m pytest tests/test_ask_prompts.py::test_prompt_mentions_sub_area_table -v`
Expected: PASS

**Step 5: Commit**

```bash
git add server/soundings/ask/prompts.py server/tests/test_ask_prompts.py
git commit -m "feat: system prompt teaches sub-area-table block"
```

---

## Slice 5: Ward-level data *(extends coverage)*

### Task 13: Add ward-level indicators to the catalogue

**Objective:** Add `ward24` to `available_at` for indicators that publish ward-level data. Start with the indicators that already have LSOA data from sources that publish at ward level (Census 2021, IMD aggregation).

**Files:**
- Modify: `catalogue/indicators.yaml` — add `ward24` to `available_at` for qualifying indicators
- Test: `server/tests/test_ask_prompts.py` (verify catalogue integrity)

**Step 1: Audit which indicators can support ward level**

Check each source:
- **ONS Census 2021** — published at ward level via Nomis → add `ward24` to census indicators
- **ONS Mid-Year Estimates** — not published at ward level → skip
- **MHCLG IMD 2025** — LSOA-only, but can be aggregated to ward → mark as `ward24` with a caveat
- **Police UK** — already works at LSOA; ward aggregation is straightforward → add

**Step 2: Update catalogue entries**

For each qualifying indicator, add `"ward24"` to its `available_at` list. For aggregated indicators, add a caveat:

```yaml
caveats:
  - "Ward-level values are aggregated from LSOA-level data and may not match ONS published ward figures exactly."
```

**Step 3: Run catalogue tests**

Run: `cd server && uv run python -m pytest tests/test_catalogue_loader.py -v`
Expected: PASS (or pre-existing failure unrelated to our changes)

**Step 4: Commit**

```bash
git add catalogue/indicators.yaml
git commit -m "feat: add ward24 to available_at for census and IMD indicators"
```

---

### Task 14: Verify full suite + update system prompt for wards

**Objective:** Ensure the system prompt mentions ward-level availability and the full test suite passes.

**Files:**
- Modify: `server/soundings/ask/prompts.py` — update geography levels section

**Step 1: Update prompt to mention ward data**

Update the geography levels paragraph from Task 1 to note:

```
Ward-level (ward24) data is available for a subset of indicators (Census,
IMD). Ward values for IMD are aggregated from LSOA-level data.
```

**Step 2: Write test**

```python
def test_prompt_mentions_ward_data_availability():
    prompt = SystemPromptBuilder().build()
    assert "ward" in prompt.lower()
    # Should note ward data is partial
    assert "subset" in prompt.lower() or "limited" in prompt.lower()
```

**Step 3: Run full test suite**

Run: `cd server && uv run python -m pytest --tb=short -q`
Expected: All new tests pass, only pre-existing failures remain

Run: `cd ui && npx vitest run`
Expected: PASS

Run: `cd server && uv run ruff check soundings/ tests/ && uv run mypy soundings/`
Expected: clean

**Step 4: Commit**

```bash
git add server/soundings/ask/prompts.py server/tests/test_ask_prompts.py
git commit -m "feat: prompt mentions ward-level data availability"
```

---

## Summary of Changes

| Slice | What | Tasks | Key files |
|-------|------|-------|-----------|
| 1 | Prompt + AskBox | 1-3 | `prompts.py`, `AskBox.astro` |
| 2 | `get_sub_areas` tool | 4-7 | `get_sub_areas.py`, `dispatcher.py`, `prompts.py` |
| 3 | Neighbourhood comparison | 8-9 | `compare_places.py`, `orchestrator.py`, `prompts.py` |
| 4 | UI rendering | 10-12 | `blocks.py`, `ask_page.ts`, `prompts.py` |
| 5 | Ward-level data | 13-14 | `indicators.yaml`, `prompts.py` |

**Parallelisable:** Tasks 1-3 (Slice 1) can run in parallel with Task 4-5 (Slice 2 model + query) since they touch different files. Tasks 10-11 (UI block + renderer) can run in parallel with Task 8 (compare_places extension) since they touch different files.

**Deferred (not in this plan):**
- Interactive clickable LSOA maps (major UI work, separate plan)
- Overture Maps integration (deferred to Phase 7)
- Postcode → finest available level auto-selection (the prompt guides Claude to do this, but a code-level default would need a find_place change)
- Ward-level seeding of boundaries (already have them — just need indicator data, which this plan adds via catalogue updates)

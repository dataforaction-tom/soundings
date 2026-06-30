# Slice 1: New Chart Block Types + Prompt Integration Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add three new chart block types (distribution, composition, scatter) to the ask interface, a `get_peer_distribution` server tool to feed them, and update the system prompt so Claude actually uses these charts in answers.

**Architecture:** New Pydantic block models in `blocks.py` → new `get_peer_distribution` tool (SQL peer values via existing orchestrator) → new Observable Plot renderers in `chart.ts` → new block renderers in `ask_page.ts` → updated system prompt with chart selection guidance → updated dispatcher to register the new tool.

**Tech Stack:** Python 3.12 / Pydantic v2 / SQLAlchemy async (server), TypeScript / Observable Plot / linkedom (UI)

---

## Task 1: Add `DistributionChartBlock` to block schema

**Objective:** Add the distribution-chart block type to the Pydantic schema.

**Files:**
- Modify: `server/soundings/ask/blocks.py`
- Test: `server/tests/test_ask_blocks.py`

**Step 1: Write failing tests**

Add to `server/tests/test_ask_blocks.py`:

```python
from soundings.ask.blocks import DistributionChartBlock

def test_distribution_chart_block_valid():
    b = DistributionChartBlock(
        type="distribution-chart",
        indicator_key="population.total",
        place_id="ltla24:E06000047",
    )
    assert b.indicator_key == "population.total"
    assert b.place_id == "ltla24:E06000047"
    assert b.caption is None

def test_distribution_chart_block_with_caption():
    b = DistributionChartBlock(
        type="distribution-chart",
        indicator_key="deprivation.imd.score",
        place_id="ltla24:E06000047",
        caption="IMD score distribution across peer LTLAs",
    )
    assert b.caption == "IMD score distribution across peer LTLAs"

def test_distribution_chart_block_counts_as_visual():
    """DistributionChartBlock should count toward the visual block cap."""
    visual = [
        DistributionChartBlock(
            type="distribution-chart",
            indicator_key=f"k{i}",
            place_id="ltla24:E06000047",
        )
        for i in range(12)
    ]
    text = [TextBlock(type="text", markdown="intro")]
    args = ComposeAnswerArgs(blocks=text + visual)
    assert sum(1 for b in args.blocks if b.type == "distribution-chart") == 10

def test_distribution_chart_block_discriminator():
    _adapter = TypeAdapter(AnswerBlock)
    raw = {
        "type": "distribution-chart",
        "indicator_key": "population.total",
        "place_id": "ltla24:E06000047",
    }
    b = _adapter.validate_python(raw)
    assert isinstance(b, DistributionChartBlock)
```

**Step 2: Run tests to verify failure**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest tests/test_ask_blocks.py -k distribution -v`
Expected: FAIL — `ImportError: cannot import name 'DistributionChartBlock'`

**Step 3: Write minimal implementation**

Add to `server/soundings/ask/blocks.py`:

```python
class DistributionChartBlock(BaseModel):
    type: Literal["distribution-chart"]
    indicator_key: str
    place_id: str
    caption: str | None = None
```

Add `"distribution-chart"` to `_VISUAL_TYPES`.
Add `DistributionChartBlock` to the `AnswerBlock` union.

**Step 4: Run tests to verify pass**

Run: same command as Step 2.
Expected: 4 passed.

Run full block tests: `uv run pytest tests/test_ask_blocks.py -v`
Expected: all pass, no regressions.

**Step 5: Commit**

```bash
git add server/soundings/ask/blocks.py server/tests/test_ask_blocks.py
git commit -m "feat: add distribution-chart block type to ask schema"
```

---

## Task 2: Add `CompositionChartBlock` to block schema

**Objective:** Add the composition-chart block (donut/pie) with inline segment data.

**Files:**
- Modify: `server/soundings/ask/blocks.py`
- Test: `server/tests/test_ask_blocks.py`

**Step 1: Write failing tests**

Add to `server/tests/test_ask_blocks.py`:

```python
from soundings.ask.blocks import CompositionChartBlock, CompositionSegment

def test_composition_chart_block_valid():
    b = CompositionChartBlock(
        type="composition-chart",
        title="Charity income distribution",
        segments=[
            CompositionSegment(label="Under £10k", value=412),
            CompositionSegment(label="£10k-£100k", value=301),
            CompositionSegment(label="£100k-£1m", value=198),
        ],
    )
    assert b.title == "Charity income distribution"
    assert len(b.segments) == 3
    assert b.caption is None

def test_composition_chart_block_with_caption():
    b = CompositionChartBlock(
        type="composition-chart",
        title="Age structure",
        segments=[CompositionSegment(label="Under 18", value=22.5)],
        caption="Population by age band",
    )
    assert b.caption == "Population by age band"

def test_composition_segment_optional_colour():
    s = CompositionSegment(label="Test", value=10)
    assert s.colour is None
    s2 = CompositionSegment(label="Test", value=10, colour="#4a7c59")
    assert s2.colour == "#4a7c59"

def test_composition_chart_block_counts_as_visual():
    visual = [
        CompositionChartBlock(
            type="composition-chart",
            title=f"Chart {i}",
            segments=[CompositionSegment(label="A", value=1)],
        )
        for i in range(12)
    ]
    text = [TextBlock(type="text", markdown="intro")]
    args = ComposeAnswerArgs(blocks=text + visual)
    assert sum(1 for b in args.blocks if b.type == "composition-chart") == 10

def test_composition_chart_block_discriminator():
    _adapter = TypeAdapter(AnswerBlock)
    raw = {
        "type": "composition-chart",
        "title": "Test",
        "segments": [{"label": "A", "value": 1}],
    }
    b = _adapter.validate_python(raw)
    assert isinstance(b, CompositionChartBlock)
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_ask_blocks.py -k composition -v`
Expected: FAIL — `ImportError`

**Step 3: Write minimal implementation**

Add to `server/soundings/ask/blocks.py`:

```python
class CompositionSegment(BaseModel):
    label: str
    value: float
    colour: str | None = None

class CompositionChartBlock(BaseModel):
    type: Literal["composition-chart"]
    title: str
    segments: list[CompositionSegment]
    caption: str | None = None
```

Add `"composition-chart"` to `_VISUAL_TYPES`.
Add `CompositionChartBlock` to the `AnswerBlock` union.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_ask_blocks.py -k composition -v`
Expected: 6 passed.

Run full block tests: `uv run pytest tests/test_ask_blocks.py -v`
Expected: all pass.

**Step 5: Commit**

```bash
git add server/soundings/ask/blocks.py server/tests/test_ask_blocks.py
git commit -m "feat: add composition-chart block type with inline segments"
```

---

## Task 3: Add `ScatterPlotBlock` to block schema

**Objective:** Add the scatter-plot block for two-indicator correlation.

**Files:**
- Modify: `server/soundings/ask/blocks.py`
- Test: `server/tests/test_ask_blocks.py`

**Step 1: Write failing tests**

Add to `server/tests/test_ask_blocks.py`:

```python
from soundings.ask.blocks import ScatterPlotBlock

def test_scatter_plot_block_valid():
    b = ScatterPlotBlock(
        type="scatter-plot",
        x_indicator_key="deprivation.imd.score",
        y_indicator_key="health.life_expectancy.female",
        place_id="ltla24:E06000047",
    )
    assert b.x_indicator_key == "deprivation.imd.score"
    assert b.y_indicator_key == "health.life_expectancy.female"
    assert b.caption is None

def test_scatter_plot_block_with_caption():
    b = ScatterPlotBlock(
        type="scatter-plot",
        x_indicator_key="deprivation.imd.score",
        y_indicator_key="health.life_expectancy.female",
        place_id="ltla24:E06000047",
        caption="Deprivation vs female life expectancy",
    )
    assert b.caption == "Deprivation vs female life expectancy"

def test_scatter_plot_block_counts_as_visual():
    visual = [
        ScatterPlotBlock(
            type="scatter-plot",
            x_indicator_key=f"k{i}",
            y_indicator_key=f"y{i}",
            place_id="ltla24:E06000047",
        )
        for i in range(12)
    ]
    text = [TextBlock(type="text", markdown="intro")]
    args = ComposeAnswerArgs(blocks=text + visual)
    assert sum(1 for b in args.blocks if b.type == "scatter-plot") == 10

def test_scatter_plot_block_discriminator():
    _adapter = TypeAdapter(AnswerBlock)
    raw = {
        "type": "scatter-plot",
        "x_indicator_key": "deprivation.imd.score",
        "y_indicator_key": "health.life_expectancy.female",
        "place_id": "ltla24:E06000047",
    }
    b = _adapter.validate_python(raw)
    assert isinstance(b, ScatterPlotBlock)
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_ask_blocks.py -k scatter -v`
Expected: FAIL — `ImportError`

**Step 3: Write minimal implementation**

Add to `server/soundings/ask/blocks.py`:

```python
class ScatterPlotBlock(BaseModel):
    type: Literal["scatter-plot"]
    x_indicator_key: str
    y_indicator_key: str
    place_id: str
    caption: str | None = None
```

Add `"scatter-plot"` to `_VISUAL_TYPES`.
Add `ScatterPlotBlock` to the `AnswerBlock` union.

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_ask_blocks.py -k scatter -v`
Expected: 4 passed.

Run full block tests: `uv run pytest tests/test_ask_blocks.py -v`
Expected: all pass.

**Step 5: Commit**

```bash
git add server/soundings/ask/blocks.py server/tests/test_ask_blocks.py
git commit -m "feat: add scatter-plot block type to ask schema"
```

---

## Task 4: Create `get_peer_distribution` tool — contract + input/output

**Objective:** Create the tool module with Pydantic models, tool spec, and the async function that calls the orchestrator's existing `_peer_values_loader` SQL to get all peer values for an indicator.

**Files:**
- Create: `server/soundings/tools/get_peer_distribution.py`
- Test: `server/tests/test_get_peer_distribution.py`

**Step 1: Write failing tests**

Create `server/tests/test_get_peer_distribution.py`:

```python
"""Unit tests for get_peer_distribution tool."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from soundings.tools.get_peer_distribution import (
    GetPeerDistributionInput,
    GetPeerDistributionOutput,
    get_peer_distribution,
    tool_spec,
)


def test_tool_spec_has_name_and_schema():
    spec = tool_spec()
    assert spec["name"] == "get_peer_distribution"
    assert "input_schema" in spec
    assert "output_schema" in spec

def test_input_model_valid():
    m = GetPeerDistributionInput(
        indicator_key="population.total",
        place_id="ltla24:E06000047",
    )
    assert m.indicator_key == "population.total"
    assert m.place_id == "ltla24:E06000047"
    assert m.period is None

def test_output_model_valid():
    m = GetPeerDistributionOutput(
        indicator_key="population.total",
        place_id="ltla24:E06000047",
        focal_value=196000,
        peer_values=[200000, 150000, 180000],
        peer_count=3,
        unit="people",
        period="2023",
    )
    assert m.focal_value == 196000
    assert m.peer_count == 3

@pytest.mark.asyncio
async def test_get_peer_distribution_calls_orchestrator():
    """Verify the tool delegates to the orchestrator's peer value loader."""
    mock_orch = MagicMock()
    mock_orch._peer_values_loader = AsyncMock(
        return_value=(
            {"ltla24:E06000047": 196000, "ltla24:E08000029": 200000},
            "2023",
        )
    )
    mock_orch._load_indicator_meta = AsyncMock(
        return_value={"unit": "people", "label": "Population total"}
    )
    mock_orch._enforce_level = AsyncMock(return_value=None)

    input_ = GetPeerDistributionInput(
        indicator_key="population.total",
        place_id="ltla24:E06000047",
    )
    result = await get_peer_distribution(input_, mock_orch)
    assert result.indicator_key == "population.total"
    assert result.place_id == "ltla24:E06000047"
    assert result.focal_value == 196000
    assert result.peer_count == 2  # both peers including focal
    assert result.unit == "people"
    assert result.period == "2023"
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_get_peer_distribution.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

Create `server/soundings/tools/get_peer_distribution.py`:

```python
"""get_peer_distribution tool — returns all peer values for an indicator.

Used by the ask interface to feed distribution charts and scatter plots.
Reuses the orchestrator's existing _peer_values_loader SQL path.
"""

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from soundings.contracts.source_ref import SourceRef

if TYPE_CHECKING:
    from soundings.orchestration.orchestrator import IndicatorOrchestrator


class GetPeerDistributionInput(BaseModel):
    indicator_key: str
    place_id: str
    period: str | None = None


class GetPeerDistributionOutput(BaseModel):
    indicator_key: str
    place_id: str
    focal_value: float | None
    peer_values: list[float] = Field(default_factory=list)
    peer_count: int
    unit: str
    period: str
    sources: list[SourceRef] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


TOOL_NAME = "get_peer_distribution"
TOOL_DESCRIPTION = (
    "Get the full distribution of an indicator's values across all "
    "same-type peer places, plus the focal place's value. Use this "
    "when you want to show a histogram, density plot, or scatter plot "
    "that needs all peer values — not just the highlighted subset "
    "returned by compare_places."
)


def tool_spec() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": GetPeerDistributionInput.model_json_schema(),
        "output_schema": GetPeerDistributionOutput.model_json_schema(),
    }


async def get_peer_distribution(
    input: GetPeerDistributionInput,
    orchestrator: "IndicatorOrchestrator",
) -> GetPeerDistributionOutput:
    place_id = input.place_id
    peer_type, _, _ = place_id.partition(":")

    # Reuse the existing loader path — same SQL as compare_places.
    await orchestrator._enforce_level(input.indicator_key, place_id)
    peer_values, period_used = await orchestrator._peer_values_loader(
        indicator_key=input.indicator_key,
        peer_type=peer_type,
        period=input.period,
    )

    focal_value = peer_values.get(place_id)
    # Exclude nulls from the distribution values list.
    all_values = [v for v in peer_values.values() if v is not None]

    meta = await orchestrator._load_indicator_meta(input.indicator_key)
    unit = meta.get("unit", "value") if meta else "value"

    return GetPeerDistributionOutput(
        indicator_key=input.indicator_key,
        place_id=place_id,
        focal_value=focal_value,
        peer_values=all_values,
        peer_count=len(all_values),
        unit=unit,
        period=str(period_used),
    )
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_get_peer_distribution.py -v`
Expected: 5 passed.

**Step 5: Commit**

```bash
git add server/soundings/tools/get_peer_distribution.py server/tests/test_get_peer_distribution.py
git commit -m "feat: add get_peer_distribution tool for chart data"
```

---

## Task 5: Register `get_peer_distribution` in the dispatcher

**Objective:** Add the new tool to the ask dispatcher's handler map and tool specs so Claude can call it during the ask loop.

**Files:**
- Modify: `server/soundings/ask/dispatcher.py`
- Test: `server/tests/test_ask_dispatcher.py`

**Step 1: Write failing tests**

Add to `server/tests/test_ask_dispatcher.py`:

```python
from soundings.tools.get_peer_distribution import tool_spec as get_peer_dist_spec

def test_dispatcher_includes_get_peer_distribution():
    """The dispatcher should list get_peer_distribution in its tool specs."""
    state = MagicMock()
    state.engine = MagicMock()
    dispatcher = ToolDispatcher(state)
    specs = dispatcher.tool_specs()
    names = [s["name"] for s in specs]
    assert "get_peer_distribution" in names

def test_dispatcher_has_handler_for_get_peer_distribution():
    """The dispatcher should have a handler for get_peer_distribution."""
    state = MagicMock()
    state.engine = MagicMock()
    dispatcher = ToolDispatcher(state)
    assert "get_peer_distribution" in dispatcher._handlers
```

**Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_ask_dispatcher.py -k peer_distribution -v`
Expected: FAIL — `AssertionError: 'get_peer_distribution' not in names`

**Step 3: Write minimal implementation**

In `server/soundings/ask/dispatcher.py`, add to the imports:

```python
from soundings.tools.get_peer_distribution import (
    GetPeerDistributionInput,
    get_peer_distribution,
)
from soundings.tools.get_peer_distribution import (
    tool_spec as get_peer_dist_spec,
)
```

Add to `tool_specs()` return list:

```python
get_peer_dist_spec(),
```

Add to `_handlers` dict:

```python
"get_peer_distribution": self._handle_get_peer_distribution,
```

Add handler method:

```python
async def _handle_get_peer_distribution(self, args: dict[str, Any]) -> dict[str, Any]:
    model = GetPeerDistributionInput.model_validate(args)
    result = await get_peer_distribution(model, self._state.orchestrator)
    return result.model_dump(mode="json")
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_ask_dispatcher.py -k peer_distribution -v`
Expected: 2 passed.

Run full dispatcher tests: `uv run pytest tests/test_ask_dispatcher.py -v`
Expected: all pass.

**Step 5: Commit**

```bash
git add server/soundings/ask/dispatcher.py server/tests/test_ask_dispatcher.py
git commit -m "feat: register get_peer_distribution in ask dispatcher"
```

---

## Task 6: Add `renderDistributionChart` to chart.ts

**Objective:** Observable Plot renderer that produces a histogram of peer values with the focal place's value marked by a vertical rule line.

**Files:**
- Modify: `ui/src/lib/chart.ts`
- Test: `ui/src/lib/__tests__/chart.test.ts` (create if doesn't exist)

**Step 1: Write failing tests**

Create `ui/src/lib/__tests__/chart.test.ts` (or add to existing):

```typescript
import { describe, it, expect, vi } from "vitest";

// Mock dom-polyfill before importing chart
vi.mock("../dom-polyfill", () => ({}));

import { renderDistributionChart } from "../chart";

describe("renderDistributionChart", () => {
  it("returns empty string for empty values", () => {
    const result = renderDistributionChart(
      { peer_values: [], focal_value: null, unit: "people", caption: null },
      {},
    );
    expect(result).toBe("");
  });

  it("returns SVG string with histogram and focal rule", () => {
    const result = renderDistributionChart(
      {
        peer_values: [100, 200, 300, 400, 500, 150, 250],
        focal_value: 250,
        unit: "people",
        caption: "Test distribution",
      },
      { containerWidth: 480 },
    );
    expect(result).toContain("<svg");
    expect(result).toContain("Distribution");
    expect(result.length).toBeGreaterThan(100);
  });

  it("includes accessibility title and desc", () => {
    const result = renderDistributionChart(
      {
        peer_values: [1, 2, 3, 4, 5],
        focal_value: 3,
        unit: "score",
        caption: "Test",
      },
      {},
    );
    expect(result).toContain("<title>");
    expect(result).toContain("<desc>");
  });
});
```

**Step 2: Run tests to verify failure**

Run: `cd ui && npx vitest run src/lib/__tests__/chart.test.ts`
Expected: FAIL — `renderDistributionChart` not exported

**Step 3: Write minimal implementation**

Add to `ui/src/lib/chart.ts`:

```typescript
// --- Distribution chart -------------------------------------------------

export interface DistributionChartInput {
  peer_values: number[];
  focal_value: number | null;
  unit: string;
  caption?: string | null;
}

export function renderDistributionChart(
  input: DistributionChartInput,
  opts: { containerWidth?: number; width?: number; height?: number } = {},
): string {
  if (input.peer_values.length === 0) return "";

  const width = opts.containerWidth ?? opts.width ?? 480;
  const height = opts.height ?? 220;

  // Build data array with a flag for the focal point.
  const data = input.peer_values.map((v) => ({ value: v, is_focal: v === input.focal_value }));

  const node = Plot.plot({
    width,
    height,
    marginTop: 16,
    marginRight: 16,
    marginBottom: 36,
    marginLeft: 48,
    style: {
      background: "transparent",
      fontSize: "12px",
      fontFamily: "system-ui, sans-serif",
    },
    x: { label: input.unit, nice: true },
    y: { grid: true, label: "Peer places", nice: true },
    marks: [
      Plot.rectY(
        data,
        Plot.binX({ y: "count" }, { x: "value", fill: "#1a2f4e", fillOpacity: 0.6 }),
      ),
      ...(input.focal_value !== null
        ? [Plot.ruleX([input.focal_value], { stroke: "#4a7c59", strokeWidth: 2.5 })]
        : []),
    ],
  });

  return svgWithA11y(
    node,
    "Distribution chart",
    `Histogram of peer values for ${input.unit}${input.caption ? ": " + input.caption : ""}.`,
  );
}
```

**Step 4: Run tests to verify pass**

Run: `cd ui && npx vitest run src/lib/__tests__/chart.test.ts`
Expected: 3 passed.

**Step 5: Commit**

```bash
git add ui/src/lib/chart.ts ui/src/lib/__tests__/chart.test.ts
git commit -m "feat: add renderDistributionChart to chart.ts"
```

---

## Task 7: Add `renderCompositionChart` to chart.ts

**Objective:** Donut chart renderer for share-of-whole data (income buckets, age structure, etc.).

**Files:**
- Modify: `ui/src/lib/chart.ts`
- Test: `ui/src/lib/__tests__/chart.test.ts`

**Step 1: Write failing tests**

Add to `ui/src/lib/__tests__/chart.test.ts`:

```typescript
import { renderCompositionChart } from "../chart";

describe("renderCompositionChart", () => {
  it("returns empty string for empty segments", () => {
    const result = renderCompositionChart(
      { title: "Test", segments: [], caption: null },
      {},
    );
    expect(result).toBe("");
  });

  it("returns SVG with donut arcs", () => {
    const result = renderCompositionChart(
      {
        title: "Income distribution",
        segments: [
          { label: "Under £10k", value: 412 },
          { label: "£10k-£100k", value: 301 },
          { label: "£100k-£1m", value: 198 },
        ],
        caption: "Charity income bands",
      },
      { containerWidth: 480 },
    );
    expect(result).toContain("<svg");
    expect(result).toContain("Composition");
  });

  it("uses PALETTE colours when no explicit colour provided", () => {
    const result = renderCompositionChart(
      {
        title: "Test",
        segments: [{ label: "A", value: 50 }, { label: "B", value: 50 }],
        caption: null,
      },
      {},
    );
    expect(result).toContain("<svg");
  });
});
```

**Step 2: Run tests to verify failure**

Run: `cd ui && npx vitest run src/lib/__tests__/chart.test.ts -k composition`
Expected: FAIL — `renderCompositionChart` not exported

**Step 3: Write minimal implementation**

Add to `ui/src/lib/chart.ts`:

```typescript
// --- Composition chart (donut) ------------------------------------------

export interface CompositionSegmentInput {
  label: string;
  value: number;
  colour?: string | null;
}

export interface CompositionChartInput {
  title: string;
  segments: CompositionSegmentInput[];
  caption?: string | null;
}

export function renderCompositionChart(
  input: CompositionChartInput,
  opts: { containerWidth?: number; width?: number; height?: number } = {},
): string {
  if (input.segments.length === 0) return "";

  const width = opts.containerWidth ?? opts.width ?? 480;
  const height = opts.height ?? 260;
  const radius = Math.min(width, height) / 2 - 40;

  // Assign colours: explicit override → PALETTE cycle.
  const segments = input.segments.map((s, i) => ({
    ...s,
    colour: s.colour ?? PALETTE[i % PALETTE.length],
  }));

  const total = segments.reduce((sum, s) => sum + s.value, 0);

  const node = Plot.plot({
    width,
    height,
    marginTop: 16,
    marginRight: 16,
    marginBottom: 36,
    marginLeft: 16,
    style: {
      background: "transparent",
      fontSize: "12px",
      fontFamily: "system-ui, sans-serif",
    },
    marks: [
      Plot.arc(
        segments,
        {
          transform: (d) => ({
            ...d,
            startAngle: 0,
            endAngle: (d.value / total) * 2 * Math.PI,
          }),
          r: radius,
          stroke: "#faf9f6",
          strokeWidth: 2,
          fill: "colour",
        },
      ),
      Plot.text(segments, {
        text: (d: CompositionSegmentInput) =>
          `${d.label}: ${((d.value / total) * 100).toFixed(0)}%`,
        fontSize: 11,
        fill: "#333",
        dx: 0,
        dy: radius + 20,
      }),
    ],
  });

  return svgWithA11y(
    node,
    "Composition chart",
    `Donut chart showing ${input.title}${input.caption ? ": " + input.caption : ""}.`,
  );
}
```

**Step 4: Run tests to verify pass**

Run: `cd ui && npx vitest run src/lib/__tests__/chart.test.ts -k composition`
Expected: 3 passed.

**Step 5: Commit**

```bash
git add ui/src/lib/chart.ts ui/src/lib/__tests__/chart.test.ts
git commit -m "feat: add renderCompositionChart (donut) to chart.ts"
```

---

## Task 8: Add `renderScatterPlot` to chart.ts

**Objective:** Scatter plot renderer showing two indicators across peer places, with the focal place highlighted.

**Files:**
- Modify: `ui/src/lib/chart.ts`
- Test: `ui/src/lib/__tests__/chart.test.ts`

**Step 1: Write failing tests**

Add to `ui/src/lib/__tests__/chart.test.ts`:

```typescript
import { renderScatterPlot } from "../chart";

describe("renderScatterPlot", () => {
  it("returns empty string for empty data", () => {
    const result = renderScatterPlot(
      {
        points: [],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy",
        caption: null,
      },
      {},
    );
    expect(result).toBe("");
  });

  it("returns SVG with scatter dots and focal point highlighted", () => {
    const result = renderScatterPlot(
      {
        points: [
          { place_id: "ltla24:A", x_value: 10, y_value: 80, is_focal: false },
          { place_id: "ltla24:B", x_value: 30, y_value: 75, is_focal: false },
          { place_id: "ltla24:E06000047", x_value: 25, y_value: 78, is_focal: true },
        ],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy (years)",
        caption: "Deprivation vs life expectancy",
      },
      { containerWidth: 480 },
    );
    expect(result).toContain("<svg");
    expect(result).toContain("Scatter");
  });
});
```

**Step 2: Run tests to verify failure**

Run: `cd ui && npx vitest run src/lib/__tests__/chart.test.ts -k scatter`
Expected: FAIL — `renderScatterPlot` not exported

**Step 3: Write minimal implementation**

Add to `ui/src/lib/chart.ts`:

```typescript
// --- Scatter plot ------------------------------------------------------

export interface ScatterPoint {
  place_id: string;
  x_value: number;
  y_value: number;
  is_focal: boolean;
}

export interface ScatterPlotInput {
  points: ScatterPoint[];
  focal_place_id: string;
  x_label: string;
  y_label: string;
  caption?: string | null;
}

export function renderScatterPlot(
  input: ScatterPlotInput,
  opts: { containerWidth?: number; width?: number; height?: number } = {},
): string {
  if (input.points.length === 0) return "";

  const width = opts.containerWidth ?? opts.width ?? 480;
  const height = opts.height ?? 320;

  const node = Plot.plot({
    width,
    height,
    marginTop: 16,
    marginRight: 16,
    marginBottom: 40,
    marginLeft: 56,
    style: {
      background: "transparent",
      fontSize: "12px",
      fontFamily: "system-ui, sans-serif",
    },
    x: { label: input.x_label, nice: true },
    y: { label: input.y_label, grid: true, nice: true },
    marks: [
      // Peer dots
      Plot.dot(
        input.points.filter((p) => !p.is_focal),
        { x: "x_value", y: "y_value", fill: "#1a2f4e", fillOpacity: 0.4, r: 4 },
      ),
      // Focal dot (larger, green)
      Plot.dot(
        input.points.filter((p) => p.is_focal),
        { x: "x_value", y: "y_value", fill: "#4a7c59", r: 7, stroke: "#faf9f6", strokeWidth: 1.5 },
      ),
    ],
  });

  return svgWithA11y(
    node,
    "Scatter plot",
    `Scatter plot of ${input.x_label} vs ${input.y_label}${input.caption ? ": " + input.caption : ""}.`,
  );
}
```

**Step 4: Run tests to verify pass**

Run: `cd ui && npx vitest run src/lib/__tests__/chart.test.ts -k scatter`
Expected: 2 passed.

**Step 5: Commit**

```bash
git add ui/src/lib/chart.ts ui/src/lib/__tests__/chart.test.ts
git commit -m "feat: add renderScatterPlot to chart.ts"
```

---

## Task 9: Add block renderers to ask_page.ts — distribution-chart

**Objective:** Wire the distribution-chart block to the SSE block renderer in ask_page.ts.

**Files:**
- Modify: `ui/src/scripts/ask_page.ts`

**Step 1: Write the renderer function**

Add to `ui/src/scripts/ask_page.ts` (after `renderCompareChartBlock`):

```typescript
// distribution-chart -----------------------------------------------------

interface PeerDistributionResponse {
  indicator_key: string;
  place_id: string;
  focal_value: number | null;
  peer_values: number[];
  peer_count: number;
  unit: string;
  period: string;
}

async function renderDistributionChartBlock(
  host: HTMLElement,
  block: { type: string; [k: string]: unknown },
  apiBase: string,
) {
  const indicatorKey = asString(block.indicator_key);
  const caption = asStringOrUndef(block.caption);
  const distPlaceId = asStringOrUndef(block.place_id) ?? placeId;
  if (!indicatorKey || !distPlaceId) {
    showBlockError(host, "Distribution chart missing indicator_key or place_id.");
    return;
  }
  let dist: PeerDistributionResponse;
  try {
    dist = await postJSON<PeerDistributionResponse>(
      "/v1/tools/get_peer_distribution",
      { indicator_key: indicatorKey, place_id: distPlaceId },
      apiBase,
    );
  } catch (err) {
    showBlockError(
      host,
      "Could not load distribution: " +
        (err instanceof Error ? err.message : String(err)),
    );
    return;
  }
  if (dist.peer_values.length === 0) {
    showBlockError(host, "No distribution data available.");
    return;
  }
  const { renderDistributionChart } = await import("../lib/chart");
  const svg = renderDistributionChart(
    {
      peer_values: dist.peer_values,
      focal_value: dist.focal_value,
      unit: dist.unit,
      caption,
    },
    { containerWidth: host.clientWidth || 480 },
  );
  if (!svg) {
    showBlockError(host, "No distribution data available.");
    return;
  }
  const figure = document.createElement("figure");
  figure.className = "distribution-chart-block";
  const chartDiv = document.createElement("div");
  chartDiv.className = "chart";
  chartDiv.innerHTML = svg;
  figure.appendChild(chartDiv);
  if (caption) {
    const figcaption = document.createElement("figcaption");
    figcaption.textContent = caption;
    figure.appendChild(figcaption);
  }
  host.appendChild(figure);
}
```

Add to the `switch (block.type)` in `renderBlock`:

```typescript
case "distribution-chart": {
  renderDistributionChartBlock(host, block, apiBase);
  break;
}
```

**Step 2: Verify build**

Run: `cd ui && npx tsc --noEmit`
Expected: no errors.

**Step 3: Commit**

```bash
git add ui/src/scripts/ask_page.ts
git commit -m "feat: wire distribution-chart block to ask page renderer"
```

---

## Task 10: Add block renderers to ask_page.ts — composition-chart

**Objective:** Wire the composition-chart block. This block is self-contained — the segments come directly from the block data (Claude provides them from prior tool calls like get_civil_society_profile).

**Files:**
- Modify: `ui/src/scripts/ask_page.ts`

**Step 1: Write the renderer function**

Add to `ui/src/scripts/ask_page.ts`:

```typescript
// composition-chart -----------------------------------------------------

function renderCompositionChartBlock(
  host: HTMLElement,
  block: { type: string; [k: string]: unknown },
) {
  const title = asString(block.title);
  const caption = asStringOrUndef(block.caption);
  const rawSegments = block.segments;
  if (!title || !Array.isArray(rawSegments)) {
    showBlockError(host, "Composition chart missing title or segments.");
    return;
  }
  const segments = rawSegments
    .filter((s): s is { label: string; value: number; colour?: string } =>
      typeof s === "object" && s !== null &&
      typeof (s as { label?: unknown }).label === "string" &&
      typeof (s as { value?: unknown }).value === "number",
    )
    .map((s) => ({
      label: s.label,
      value: s.value,
      ...(s.colour ? { colour: s.colour } : {}),
    }));
  if (segments.length === 0) {
    showBlockError(host, "Composition chart has no valid segments.");
    return;
  }
  // Dynamic import — chart.ts is already loaded for trend/compare, but
  // import() is idempotent.
  import("../lib/chart").then(({ renderCompositionChart }) => {
    const svg = renderCompositionChart(
      { title, segments, caption },
      { containerWidth: host.clientWidth || 480 },
    );
    if (!svg) {
      showBlockError(host, "No composition chart data available.");
      return;
    }
    const figure = document.createElement("figure");
    figure.className = "composition-chart-block";
    const chartDiv = document.createElement("div");
    chartDiv.className = "chart";
    chartDiv.innerHTML = svg;
    figure.appendChild(chartDiv);
    if (caption) {
      const figcaption = document.createElement("figcaption");
      figcaption.textContent = caption;
      figure.appendChild(figcaption);
    }
    host.appendChild(figure);
  });
}
```

Add to the `switch (block.type)`:

```typescript
case "composition-chart": {
  renderCompositionChartBlock(host, block);
  break;
}
```

**Step 2: Verify build**

Run: `cd ui && npx tsc --noEmit`
Expected: no errors.

**Step 3: Commit**

```bash
git add ui/src/scripts/ask_page.ts
git commit -m "feat: wire composition-chart block to ask page renderer"
```

---

## Task 11: Add block renderers to ask_page.ts — scatter-plot

**Objective:** Wire the scatter-plot block. This requires two `get_peer_distribution` calls (one per indicator), then combining them into scatter points.

**Files:**
- Modify: `ui/src/scripts/ask_page.ts`

**Step 1: Write the renderer function**

Add to `ui/src/scripts/ask_page.ts`:

```typescript
// scatter-plot ----------------------------------------------------------

async function renderScatterPlotBlock(
  host: HTMLElement,
  block: { type: string; [k: string]: unknown },
  apiBase: string,
) {
  const xKey = asString(block.x_indicator_key);
  const yKey = asString(block.y_indicator_key);
  const scatterPlaceId = asStringOrUndef(block.place_id) ?? placeId;
  const caption = asStringOrUndef(block.caption);
  if (!xKey || !yKey || !scatterPlaceId) {
    showBlockError(host, "Scatter plot needs x_indicator_key, y_indicator_key, and place_id.");
    return;
  }

  // Fetch both indicator distributions in parallel.
  const [xRes, yRes] = await Promise.all([
    postJSON<PeerDistributionResponse>(
      "/v1/tools/get_peer_distribution",
      { indicator_key: xKey, place_id: scatterPlaceId },
      apiBase,
    ).catch(() => null),
    postJSON<PeerDistributionResponse>(
      "/v1/tools/get_peer_distribution",
      { indicator_key: yKey, place_id: scatterPlaceId },
      apiBase,
    ).catch(() => null),
  ]);

  if (!xRes || !yRes) {
    showBlockError(host, "Could not load scatter plot data.");
    return;
  }

  // We need paired (x, y) values per place. The peer distribution returns
  // only values (not place_ids), so we can't pair them. We need to fetch
  // peer values with place_ids. This requires extending the tool output.
  // For now, use the compare_places approach: call compare_places with
  // both indicators and the full peer set to get paired values.
  // Fallback: render with the available data as best-effort.
  // TODO: extend get_peer_distribution to return place_id:value pairs.

  // Simple fallback: show two distributions side by side as text.
  showBlockError(
    host,
    "Scatter plot requires paired peer data (not yet available). Showing distribution instead.",
  );
  // Render as distribution chart for the x indicator as a fallback.
  const { renderDistributionChart } = await import("../lib/chart");
  const svg = renderDistributionChart(
    {
      peer_values: xRes.peer_values,
      focal_value: xRes.focal_value,
      unit: `${xRes.unit} vs ${yRes.unit}`,
      caption: caption ?? `${xKey} vs ${yKey}`,
    },
    { containerWidth: host.clientWidth || 480 },
  );
  if (svg) {
    const figure = document.createElement("figure");
    figure.className = "scatter-plot-block scatter-fallback";
    const chartDiv = document.createElement("div");
    chartDiv.className = "chart";
    chartDiv.innerHTML = svg;
    figure.appendChild(chartDiv);
    host.appendChild(figure);
  }
}
```

Add to the `switch (block.type)`:

```typescript
case "scatter-plot": {
  renderScatterPlotBlock(host, block, apiBase);
  break;
}
```

**Important note:** The scatter plot needs paired (x, y) values per place. The initial `get_peer_distribution` tool returns only `peer_values` (a flat list). To get paired data, we need to either:
- Extend `get_peer_distribution` to also return `place_id: value` pairs, OR
- Add a `get_peer_scatter` tool that returns paired data for two indicators

For the initial slice, we'll render a fallback distribution chart with a note. The full scatter plot is a follow-up task (see Task 12).

**Step 2: Verify build**

Run: `cd ui && npx tsc --noEmit`
Expected: no errors.

**Step 3: Commit**

```bash
git add ui/src/scripts/ask_page.ts
git commit -m "feat: wire scatter-plot block (fallback to distribution for now)"
```

---

## Task 12: Extend `get_peer_distribution` to return place_id:value pairs

**Objective:** The tool output needs `peer_place_values: list[{place_id, value}]` so the scatter plot can pair x/y values by place_id.

**Files:**
- Modify: `server/soundings/tools/get_peer_distribution.py`
- Modify: `server/tests/test_get_peer_distribution.py`

**Step 1: Write failing test**

Add to `server/tests/test_get_peer_distribution.py`:

```python
def test_output_includes_peer_place_values():
    """The output should include place_id:value pairs for pairing in scatter plots."""
    m = GetPeerDistributionOutput(
        indicator_key="population.total",
        place_id="ltla24:E06000047",
        focal_value=196000,
        peer_values=[200000, 196000],
        peer_place_values=[
            {"place_id": "ltla24:E08000029", "value": 200000},
            {"place_id": "ltla24:E06000047", "value": 196000},
        ],
        peer_count=2,
        unit="people",
        period="2023",
    )
    assert len(m.peer_place_values) == 2
    assert m.peer_place_values[0]["place_id"] == "ltla24:E08000029"
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_get_peer_distribution.py -k peer_place_values -v`
Expected: FAIL — `AttributeError` or `ValidationError` (field doesn't exist)

**Step 3: Implement**

In `server/soundings/tools/get_peer_distribution.py`, add to `GetPeerDistributionOutput`:

```python
peer_place_values: list[dict[str, Any]] = Field(default_factory=list)
```

Update `get_peer_distribution()` to populate it:

```python
peer_place_values = [
    {"place_id": pid, "value": val}
    for pid, val in peer_values.items()
    if val is not None
]
```

Add to the return:

```python
peer_place_values=peer_place_values,
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_get_peer_distribution.py -v`
Expected: all pass.

**Step 5: Commit**

```bash
git add server/soundings/tools/get_peer_distribution.py server/tests/test_get_peer_distribution.py
git commit -m "feat: add peer_place_values to get_peer_distribution output"
```

---

## Task 13: Full scatter-plot renderer using paired data

**Objective:** Replace the fallback scatter renderer with a real one that fetches paired data for both indicators and renders a proper scatter plot.

**Files:**
- Modify: `ui/src/scripts/ask_page.ts`

**Step 1: Rewrite `renderScatterPlotBlock`**

Replace the fallback implementation with:

```typescript
async function renderScatterPlotBlock(
  host: HTMLElement,
  block: { type: string; [k: string]: unknown },
  apiBase: string,
) {
  const xKey = asString(block.x_indicator_key);
  const yKey = asString(block.y_indicator_key);
  const scatterPlaceId = asStringOrUndef(block.place_id) ?? placeId;
  const caption = asStringOrUndef(block.caption);
  if (!xKey || !yKey || !scatterPlaceId) {
    showBlockError(host, "Scatter plot needs x_indicator_key, y_indicator_key, and place_id.");
    return;
  }

  const [xRes, yRes] = await Promise.all([
    postJSON<PeerDistributionResponse & { peer_place_values: { place_id: string; value: number }[] }>(
      "/v1/tools/get_peer_distribution",
      { indicator_key: xKey, place_id: scatterPlaceId },
      apiBase,
    ).catch(() => null),
    postJSON<PeerDistributionResponse & { peer_place_values: { place_id: string; value: number }[] }>(
      "/v1/tools/get_peer_distribution",
      { indicator_key: yKey, place_id: scatterPlaceId },
      apiBase,
    ).catch(() => null),
  ]);

  if (!xRes || !yRes || xRes.peer_place_values.length === 0 || yRes.peer_place_values.length === 0) {
    showBlockError(host, "Could not load scatter plot data.");
    return;
  }

  // Pair x/y values by place_id.
  const yMap = new Map(yRes.peer_place_values.map((p) => [p.place_id, p.value]));
  const points = xRes.peer_place_values
    .map((p) => {
      const yVal = yMap.get(p.place_id);
      if (yVal === undefined) return null;
      return {
        place_id: p.place_id,
        x_value: p.value,
        y_value: yVal,
        is_focal: p.place_id === scatterPlaceId,
      };
    })
    .filter((p): p is { place_id: string; x_value: number; y_value: number; is_focal: boolean } =>
      p !== null,
    );

  if (points.length === 0) {
    showBlockError(host, "No paired data available for scatter plot.");
    return;
  }

  const { renderScatterPlot } = await import("../lib/chart");
  const svg = renderScatterPlot(
    {
      points,
      focal_place_id: scatterPlaceId,
      x_label: prettyKey(xKey),
      y_label: prettyKey(yKey),
      caption,
    },
    { containerWidth: host.clientWidth || 480 },
  );
  if (!svg) {
    showBlockError(host, "No scatter plot data available.");
    return;
  }
  const figure = document.createElement("figure");
  figure.className = "scatter-plot-block";
  const chartDiv = document.createElement("div");
  chartDiv.className = "chart";
  chartDiv.innerHTML = svg;
  figure.appendChild(chartDiv);
  if (caption) {
    const figcaption = document.createElement("figcaption");
    figcaption.textContent = caption;
    figure.appendChild(figcaption);
  }
  host.appendChild(figure);
}
```

**Step 2: Verify build**

Run: `cd ui && npx tsc --noEmit`
Expected: no errors.

**Step 3: Commit**

```bash
git add ui/src/scripts/ask_page.ts
git commit -m "feat: full scatter-plot renderer with paired peer data"
```

---

## Task 14: Update system prompt with chart selection guidance

**Objective:** Update `_BLOCK_GUIDANCE` in `prompts.py` so Claude knows when to use each chart type, and add `get_peer_distribution` to the tool list in `_SCOPE_DESCRIPTION`.

**Files:**
- Modify: `server/soundings/ask/prompts.py`
- Test: `server/tests/test_ask_prompts.py`

**Step 1: Write failing tests**

Add to `server/tests/test_ask_prompts.py`:

```python
def test_prompt_mentions_distribution_chart():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "distribution-chart" in prompt

def test_prompt_mentions_composition_chart():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "composition-chart" in prompt

def test_prompt_mentions_scatter_plot():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "scatter-plot" in prompt

def test_prompt_mentions_get_peer_distribution():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "get_peer_distribution" in prompt

def test_prompt_has_chart_selection_guidance():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "Use distribution-chart" in prompt
    assert "Use composition-chart" in prompt
    assert "Use scatter-plot" in prompt
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/test_ask_prompts.py -k "distribution or composition or scatter or peer_distribution" -v`
Expected: FAIL

**Step 3: Write minimal implementation**

In `server/soundings/ask/prompts.py`, update `_SCOPE_DESCRIPTION` to add `get_peer_distribution`:

```
- get_peer_distribution: get all peer values for an indicator at a place
  (use for distribution charts and scatter plots — not for simple comparisons)
```

Update `_BLOCK_GUIDANCE` to add the new block types with selection guidance:

```
- distribution-chart: histogram of peer values with the focal place marked
  (use get_peer_distribution first, then reference the indicator_key)
- composition-chart: donut/pie chart for share-of-whole data (income buckets,
  age structure, ethnicity). Segments come from prior tool calls — include
  them inline in the block. Use when the data is naturally compositional.
- scatter-plot: two-indicator scatter with the focal place highlighted
  (call get_peer_distribution for both indicators, then reference both keys)

Chart selection guidance:
- Use trend-chart when the question is about change over time for one place
- Use compare-chart when comparing a few named places side by side
- Use distribution-chart when the question is about where a place sits
  within its peer group — shows the shape of the distribution
- Use composition-chart when the data is share-of-whole (parts of a total)
- Use scatter-plot when exploring the relationship between two indicators
- Never use more than 3 chart blocks in one answer — pick the most relevant
- Always pair charts with text explaining what the chart shows
```

**Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_ask_prompts.py -v`
Expected: all pass.

**Step 5: Commit**

```bash
git add server/soundings/ask/prompts.py server/tests/test_ask_prompts.py
git commit -m "feat: update system prompt with new chart types and selection guidance"
```

---

## Task 15: Add HTTP route for `get_peer_distribution`

**Objective:** The tool needs an HTTP endpoint at `/v1/tools/get_peer_distribution` so the ask page client-side renderer can fetch peer distribution data.

**Files:**
- Modify: `server/soundings/http/tools.py` (or wherever tool routes are registered)

**Step 1: Find existing pattern**

Read `server/soundings/http/tools.py` to see how other tools are registered.

**Step 2: Add route following existing pattern**

Add a POST route for `/v1/tools/get_peer_distribution` that calls the `get_peer_distribution` tool function, same as other tool routes.

**Step 3: Test**

Add to `server/tests/test_ask_route.py` (or `test_tools_route.py`):

```python
async def test_get_peer_distribution_route(client):
    resp = await client.post("/v1/tools/get_peer_distribution", json={
        "indicator_key": "population.total",
        "place_id": "ltla24:E06000047",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "peer_values" in data
    assert "focal_value" in data
```

**Step 4: Run tests, commit**

```bash
git add server/soundings/http/ server/tests/
git commit -m "feat: add HTTP route for get_peer_distribution tool"
```

---

## Task 16: Run full test suite + lint + type check

**Objective:** Verify everything works together.

**Step 1: Python tests**

```bash
cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m "not live" -q
```

**Step 2: Lint + type**

```bash
cd server && uv run ruff check . && uv run mypy soundings/
```

**Step 3: UI tests**

```bash
cd ui && npx vitest run
```

**Step 4: UI type check**

```bash
cd ui && npx tsc --noEmit
```

**Step 5: Commit any remaining fixes**

```bash
git add -A && git commit -m "test: full suite green for slice 1"
```

---

## Notes for subagents

- **Test DB**: Tests that need a database use `DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test"`. Non-live tests mock the DB.
- **Pre-commit hooks**: ruff + ruff-format will reformat on first commit attempt. Commit twice (first fails, second succeeds) — this is normal.
- **Observable Plot SSR**: `chart.ts` imports `./dom-polyfill` which provides linkedom. All Plot.plot() calls happen in Node SSR. Tests must mock dom-polyfill or import it first.
- **TypeScript strict**: `tsc --noEmit` must pass with zero errors.
- **Conventional commits**: `feat:`, `test:`, `docs:` prefixes only.
- **Never push**: All work is local on a feature branch.

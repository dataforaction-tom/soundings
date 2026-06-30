# Ask Interface Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build the natural-language ask interface — a Claude tool-use loop over existing Soundings tools that produces composed, narrative answers with embedded indicators, charts, and insights.

**Architecture:** A single `/v1/ask` endpoint runs a Claude tool-use loop (Anthropic SDK) that calls existing in-process tool handlers. The loop terminates on `compose_answer`, streaming typed blocks via SSE to an Astro `/ask` page. A pure-SQL `detect_insights` tool provides deterministic signals Claude narrates over. Capture middleware wraps `/v1/ask` like every other tool route.

**Tech Stack:** Python 3.12, FastAPI, Anthropic SDK, Pydantic, SQLAlchemy, SSE. Astro 4, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-05-31-ask-interface-design.md`

---

## Slice A — Server Foundation

### Task 1: Add `anthropic` dependency and config

**Objective:** Add the Anthropic Python SDK and two new settings to the server config.

**Files:**
- Modify: `server/pyproject.toml`
- Modify: `server/soundings/core/config.py`

**Step 1: Add the dependency**

In `server/pyproject.toml`, add `"anthropic>=0.40"` to the `dependencies` list (after `"httpx>=0.28"`).

**Step 2: Add config settings**

In `server/soundings/core/config.py`, add two fields to `Settings`:

```python
anthropic_api_key: str = ""
ask_model: str = "claude-sonnet-4-20250514"
```

**Step 3: Install**

Run: `cd server && uv sync`
Expected: deps installed, no errors.

**Step 4: Verify config loads**

Run: `cd server && uv run python -c "from soundings.core.config import get_settings; s = get_settings(); print(s.ask_model)"`
Expected: `claude-sonnet-4-20250514`

**Step 5: Commit**

```bash
cd /Users/tomcwxyz/code/dataforaction-tom/soundings
git add server/pyproject.toml server/uv.lock server/soundings/core/config.py
git commit -m "feat(ask): add anthropic dependency and ask config settings"
```

---

### Task 2: Create block schema (`ask/blocks.py`)

**Objective:** Pydantic models for the typed answer blocks — the single source of truth for both the Anthropic tool schema and the SSE payload.

**Files:**
- Create: `server/soundings/ask/__init__.py`
- Create: `server/soundings/ask/blocks.py`
- Create: `server/tests/test_ask_blocks.py`

**Step 1: Write failing tests**

```python
# server/tests/test_ask_blocks.py
"""Unit tests for the compose_answer block schema."""
import pytest
from pydantic import ValidationError

from soundings.ask.blocks import (
    AnswerBlock,
    ComposeAnswerArgs,
    CompareChartBlock,
    IndicatorCardBlock,
    InsightCalloutBlock,
    OrganisationsBlock,
    TextBlock,
    TrendChartBlock,
)


def test_text_block_valid():
    b = TextBlock(type="text", markdown="Hello **world**")
    assert b.type == "text"
    assert b.markdown == "Hello **world**"


def test_indicator_card_block_valid():
    b = IndicatorCardBlock(type="indicator-card", indicator_key="population.total", place_id="ltla24:E06000047")
    assert b.indicator_key == "population.total"
    assert b.period is None


def test_trend_chart_block_with_caption():
    b = TrendChartBlock(type="trend-chart", indicator_key="population.total", place_id="ltla24:E06000047", caption="Population over time")
    assert b.caption == "Population over time"


def test_compare_chart_block_defaults():
    b = CompareChartBlock(type="compare-chart", indicator_key="population.total", place_ids=["ltla24:E06000047", "ltla24:E08000029"])
    assert b.basis == "percentile"
    assert len(b.place_ids) == 2


def test_organisations_block_defaults():
    b = OrganisationsBlock(type="organisations", place_id="ltla24:E06000047")
    assert b.limit == 5


def test_insight_callout_block():
    b = InsightCalloutBlock(
        type="insight-callout",
        severity="extreme",
        headline="Bottom 5% for life expectancy",
        evidence="Stockton's female life expectancy is in the bottom decile nationally.",
    )
    assert b.severity == "extreme"
    assert b.indicator_key is None


def test_insight_callout_rejects_bad_severity():
    with pytest.raises(ValidationError):
        InsightCalloutBlock(
            type="insight-callout",
            severity="critical",
            headline="test",
            evidence="test",
        )


def test_compose_answer_rejects_unknown_block_type():
    with pytest.raises(ValidationError):
        ComposeAnswerArgs.model_validate({"blocks": [{"type": "unknown", "data": "x"}]})


def test_compose_answer_enforces_max_blocks():
    blocks = [TextBlock(type="text", markdown=f"Block {i}") for i in range(21)]
    with pytest.raises(ValidationError):
        ComposeAnswerArgs(blocks=blocks)


def test_compose_answer_enforces_max_visual_blocks():
    # 7 visual blocks (non-text) should fail
    visual = [
        IndicatorCardBlock(type="indicator-card", indicator_key=f"k{i}", place_id="ltla24:E06000047")
        for i in range(7)
    ]
    text = [TextBlock(type="text", markdown="intro")]
    with pytest.raises(ValidationError):
        ComposeAnswerArgs(blocks=text + visual)


def test_compose_answer_at_limits():
    # 20 blocks total, 6 visual — should pass
    visual = [
        IndicatorCardBlock(type="indicator-card", indicator_key=f"k{i}", place_id="ltla24:E06000047")
        for i in range(6)
    ]
    text = [TextBlock(type="text", markdown=f"Block {i}") for i in range(14)]
    args = ComposeAnswerArgs(blocks=text + visual)
    assert len(args.blocks) == 20


def test_discriminator_routes_correctly():
    raw = {"type": "text", "markdown": "hi"}
    b = AnswerBlock.model_validate(raw)
    assert isinstance(b, TextBlock)

    raw = {"type": "insight-callout", "severity": "notable", "headline": "x", "evidence": "y"}
    b = AnswerBlock.model_validate(raw)
    assert isinstance(b, InsightCalloutBlock)
```

**Step 2: Run tests to verify failure**

Run: `cd server && uv run pytest tests/test_ask_blocks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soundings.ask'`

**Step 3: Write the implementation**

```python
# server/soundings/ask/__init__.py
```

```python
# server/soundings/ask/blocks.py
"""Typed block schema for the compose_answer tool.

Single source of truth for both the Anthropic tool schema and the SSE
payload. The orchestrator validates compose_answer calls against these
models; the UI receives the same shapes via SSE.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

ComparisonBasis = Literal["percentile", "rank", "absolute", "rate"]
Severity = Literal["notable", "extreme"]

MAX_TOTAL_BLOCKS = 20
MAX_VISUAL_BLOCKS = 6

_VISUAL_TYPES = frozenset({
    "indicator-card", "trend-chart", "compare-chart", "organisations", "insight-callout",
})


class TextBlock(BaseModel):
    type: Literal["text"]
    markdown: str


class IndicatorCardBlock(BaseModel):
    type: Literal["indicator-card"]
    indicator_key: str
    place_id: str
    period: str | None = None


class TrendChartBlock(BaseModel):
    type: Literal["trend-chart"]
    indicator_key: str
    place_id: str
    caption: str | None = None


class CompareChartBlock(BaseModel):
    type: Literal["compare-chart"]
    indicator_key: str
    place_ids: list[str] = Field(min_length=2, max_length=10)
    basis: ComparisonBasis = "percentile"


class OrganisationsBlock(BaseModel):
    type: Literal["organisations"]
    place_id: str
    limit: int = 5


class InsightCalloutBlock(BaseModel):
    type: Literal["insight-callout"]
    severity: Severity
    headline: str
    indicator_key: str | None = None
    place_id: str | None = None
    evidence: str


AnswerBlock = Annotated[
    TextBlock | IndicatorCardBlock | TrendChartBlock | CompareChartBlock
    | OrganisationsBlock | InsightCalloutBlock,
    Field(discriminator="type"),
]


class ComposeAnswerArgs(BaseModel):
    blocks: list[AnswerBlock]

    @model_validator(mode="after")
    def _enforce_caps(self) -> ComposeAnswerArgs:
        if len(self.blocks) > MAX_TOTAL_BLOCKS:
            raise ValueError(
                f"Too many blocks: {len(self.blocks)} > {MAX_TOTAL_BLOCKS}"
            )
        visual_count = sum(1 for b in self.blocks if b.type in _VISUAL_TYPES)
        if visual_count > MAX_VISUAL_BLOCKS:
            raise ValueError(
                f"Too many visual blocks: {visual_count} > {MAX_VISUAL_BLOCKS}"
            )
        return self
```

**Step 4: Run tests to verify pass**

Run: `cd server && uv run pytest tests/test_ask_blocks.py -v`
Expected: 13 passed

**Step 5: Lint + type check**

Run: `cd server && uv run ruff check soundings/ask/ && uv run mypy soundings/ask/`
Expected: clean

**Step 6: Commit**

```bash
cd /Users/tomcwxyz/code/dataforaction-tom/soundings
git add server/soundings/ask/ server/tests/test_ask_blocks.py
git commit -m "feat(ask): add typed block schema with discriminator and caps"
```

---

### Task 3: Create tool dispatcher (`ask/dispatcher.py`)

**Objective:** Map Anthropic `tool_use` blocks to the right in-process Python handler. Returns serialised results. Maintains a fetch cache keyed by `(indicator_key, place_id)` and `(indicator_key, frozenset(place_ids))`.

**Files:**
- Create: `server/soundings/ask/dispatcher.py`
- Create: `server/tests/test_ask_dispatcher.py`

**Step 1: Write failing tests**

```python
# server/tests/test_ask_dispatcher.py
"""Unit tests for the tool dispatcher."""
import pytest
from soundings.ask.dispatcher import ToolDispatcher
from soundings.ask.blocks import ComposeAnswerArgs, TextBlock


class FakeGeographyService:
    async def find_place_by_postcode(self, query):
        return None
    async def find_place_by_name(self, query, geography_types=None, limit=10):
        return []


class FakeOrchestrator:
    pass


class FakeEngine:
    pass


def _make_state():
    from types import SimpleNamespace
    return SimpleNamespace(
        geography_service=FakeGeographyService(),
        orchestrator=FakeOrchestrator(),
        engine=FakeEngine(),
    )


def test_dispatcher_lists_tool_specs():
    state = _make_state()
    d = ToolDispatcher(state)
    specs = d.tool_specs()
    names = [s["name"] for s in specs]
    assert "find_place" in names
    assert "get_place_profile" in names
    assert "compare_places" in names
    assert "get_trend" in names
    assert "find_organisations_in_place" in names
    assert "get_civil_society_profile" in names
    assert "detect_insights" in names
    assert "compose_answer" in names


def test_dispatcher_compose_answer_is_terminal():
    state = _make_state()
    d = ToolDispatcher(state)
    assert d.is_terminal_tool("compose_answer")
    assert not d.is_terminal_tool("find_place")


def test_dispatcher_compose_answer_parses_blocks():
    state = _make_state()
    d = ToolDispatcher(state)
    result = d._parse_compose_answer({
        "blocks": [{"type": "text", "markdown": "Hello"}]
    })
    assert isinstance(result, ComposeAnswerArgs)
    assert len(result.blocks) == 1
    assert isinstance(result.blocks[0], TextBlock)


def test_dispatcher_compose_answer_rejects_invalid():
    state = _make_state()
    d = ToolDispatcher(state)
    with pytest.raises(ValueError):
        d._parse_compose_answer({"blocks": [{"type": "bad"}]})
```

**Step 2: Run tests to verify failure**

Run: `cd server && uv run pytest tests/test_ask_dispatcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soundings.ask.dispatcher'`

**Step 3: Write the implementation**

```python
# server/soundings/ask/dispatcher.py
"""ToolDispatcher — maps Anthropic tool_use blocks to in-process handlers.

The dispatcher is the bridge between Claude's tool-use API and the
existing Soundings tool handlers. It:

1. Exposes tool specs (name + input_schema) for the system prompt.
2. Routes incoming tool_use blocks to the right async handler.
3. Maintains a fetch cache so compose_answer can validate references.
4. Detects compose_answer as the terminal tool.
"""

from typing import Any

from soundings.ask.blocks import ComposeAnswerArgs
from soundings.tools.compare_places import (
    ComparePlacesInput,
    compare_places,
    tool_spec as compare_places_spec,
)
from soundings.tools.find_organisations_in_place import (
    FindOrganisationsInPlaceInput,
    find_organisations_in_place,
    tool_spec as find_orgs_spec,
)
from soundings.tools.find_place import (
    FindPlaceInput,
    find_place,
    tool_spec as find_place_spec,
)
from soundings.tools.get_civil_society_profile import (
    GetCivilSocietyProfileInput,
    get_civil_society_profile,
    tool_spec as get_csp_spec,
)
from soundings.tools.get_indicators import (
    GetIndicatorsInput,
    get_indicators,
    tool_spec as get_indicators_spec,
)
from soundings.tools.get_place_profile import (
    GetPlaceProfileInput,
    get_place_profile,
    tool_spec as get_place_profile_spec,
)
from soundings.tools.get_trend import (
    GetTrendInput,
    get_trend,
    tool_spec as get_trend_spec,
)

TERMINAL_TOOL = "compose_answer"


class ToolDispatcher:
    """Maps Anthropic tool_use blocks to in-process Python handlers."""

    def __init__(self, state: Any) -> None:
        self._state = state
        # Fetch cache: (indicator_key, place_id) -> IndicatorValue
        self._fetch_cache: dict[tuple[str, str], Any] = {}
        # Compare cache: (indicator_key, frozenset(place_ids)) -> Comparison
        self._compare_cache: dict[tuple[str, frozenset[str]], Any] = {}
        # SourceRef accumulator
        self._sources: list[Any] = []

    def tool_specs(self) -> list[dict[str, object]]:
        """Return all tool specs for the Anthropic API request."""
        return [
            find_place_spec(),
            get_indicators_spec(),
            get_place_profile_spec(),
            compare_places_spec(),
            get_trend_spec(),
            find_orgs_spec(),
            get_csp_spec(),
            # detect_insights spec added in Task 4
            {
                "name": "compose_answer",
                "description": (
                    "Compose the final answer. Call this once you have enough "
                    "data to answer the user's question. Pass an ordered list "
                    "of blocks (text, indicator-card, trend-chart, compare-chart, "
                    "organisations, insight-callout). Max 20 blocks, 6 visual."
                ),
                "input_schema": ComposeAnswerArgs.model_json_schema(),
            },
        ]

    def is_terminal_tool(self, tool_name: str) -> bool:
        return tool_name == TERMINAL_TOOL

    def _parse_compose_answer(self, args: dict[str, Any]) -> ComposeAnswerArgs:
        return ComposeAnswerArgs.model_validate(args)

    async def dispatch(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Route a tool_use block to the right handler. Returns JSON-serialisable dict."""
        if tool_name == TERMINAL_TOOL:
            # compose_answer is parsed by the orchestrator, not dispatched here
            parsed = self._parse_compose_answer(tool_input)
            return parsed.model_dump(mode="json")

        handler = self._handlers.get(tool_name)
        if handler is None:
            raise ValueError(f"Unknown tool: {tool_name}")
        return await handler(tool_input)

    @property
    def _handlers(self) -> dict[str, Any]:
        return {
            "find_place": self._handle_find_place,
            "get_indicators": self._handle_get_indicators,
            "get_place_profile": self._handle_get_place_profile,
            "compare_places": self._handle_compare_places,
            "get_trend": self._handle_get_trend,
            "find_organisations_in_place": self._handle_find_organisations,
            "get_civil_society_profile": self._handle_get_csp,
        }

    async def _handle_find_place(self, args: dict[str, Any]) -> dict[str, Any]:
        result = await find_place(
            FindPlaceInput(**args), self._state.geography_service
        )
        return result.model_dump(mode="json")

    async def _handle_get_indicators(self, args: dict[str, Any]) -> dict[str, Any]:
        result = await get_indicators(
            GetIndicatorsInput(**args), self._state.orchestrator
        )
        return result.model_dump(mode="json")

    async def _handle_get_place_profile(self, args: dict[str, Any]) -> dict[str, Any]:
        result = await get_place_profile(
            GetPlaceProfileInput(**args),
            self._state.orchestrator,
            self._state.engine,
        )
        return result.model_dump(mode="json")

    async def _handle_compare_places(self, args: dict[str, Any]) -> dict[str, Any]:
        result = await compare_places(
            ComparePlacesInput(**args), self._state.orchestrator
        )
        return result.model_dump(mode="json")

    async def _handle_get_trend(self, args: dict[str, Any]) -> dict[str, Any]:
        result = await get_trend(
            GetTrendInput(**args), self._state.orchestrator
        )
        return result.model_dump(mode="json")

    async def _handle_find_organisations(self, args: dict[str, Any]) -> dict[str, Any]:
        result = await find_organisations_in_place(
            FindOrganisationsInPlaceInput(**args), self._state.orchestrator
        )
        return result.model_dump(mode="json")

    async def _handle_get_csp(self, args: dict[str, Any]) -> dict[str, Any]:
        result = await get_civil_society_profile(
            GetCivilSocietyProfileInput(**args), self._state.orchestrator
        )
        return result.model_dump(mode="json")

    @property
    def sources(self) -> list[Any]:
        return self._sources
```

**Step 4: Run tests to verify pass**

Run: `cd server && uv run pytest tests/test_ask_dispatcher.py -v`
Expected: 4 passed

**Step 5: Lint + type check**

Run: `cd server && uv run ruff check soundings/ask/dispatcher.py && uv run mypy soundings/ask/dispatcher.py`
Expected: clean

**Step 6: Commit**

```bash
git add server/soundings/ask/dispatcher.py server/tests/test_ask_dispatcher.py
git commit -m "feat(ask): add tool dispatcher mapping Anthropic tool_use to in-process handlers"
```

---

### Task 4: Create `detect_insights` tool

**Objective:** Pure-SQL deterministic insight detector. Returns signals for extreme percentiles, peer divergence, and trend reversals.

**Files:**
- Create: `server/soundings/tools/detect_insights.py`
- Create: `server/tests/test_detect_insights.py`

**Step 1: Write failing tests**

```python
# server/tests/test_detect_insights.py
"""Integration tests for the detect_insights tool."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from soundings.db.engine import get_engine
from soundings.tools.detect_insights import (
    DetectInsightsInput,
    DetectInsightsOutput,
    InsightSignal,
    detect_insights,
)

pytestmark = pytest.mark.integration


async def _seed_places_and_values():
    """Seed 10 LTLAs with population.total values spanning a wide range."""
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.loader_run"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        run = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO data.loader_run (id, source_id, started_at, finished_at, status, rows_written) "
                "VALUES (:id, 'ons.mid_year_estimates', :s, :f, 'ok', 10)"
            ),
            {"id": run, "s": now - timedelta(minutes=5), "f": now},
        )
        # 10 LTLAs — one at 10k (bottom decile), one at 500k (top decile)
        pops = [10000, 80000, 120000, 150000, 180000, 200000, 220000, 250000, 300000, 500000]
        for i, pop in enumerate(pops):
            place_id = f"ltla24:E{i:07d}"
            await conn.execute(
                text(
                    "INSERT INTO geography.place (id, type, code, name) "
                    "VALUES (:id, 'ltla24', :code, :name)"
                ),
                {"id": place_id, "code": f"E{i:07d}", "name": f"Place {i}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO data.indicator_value "
                    "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) "
                    "VALUES (:pid, 'population.total', '2024', :val, 'ons.mid_year_estimates', :ret, '[]'::jsonb)"
                ),
                {"pid": place_id, "val": pop, "ret": now},
            )
    return "ltla24:E0000000"  # lowest place


async def test_extreme_percentile_bottom():
    target_id = await _seed_places_and_values()
    result = await detect_insights(
        DetectInsightsInput(place_id=target_id, indicator_keys=["population.total"]),
        get_engine(),
    )
    assert isinstance(result, DetectInsightsOutput)
    assert len(result.signals) >= 1
    # The lowest value (10k) should be flagged as extreme (bottom decile)
    sig = next(s for s in result.signals if s.kind == "extreme_percentile")
    assert sig.severity == "extreme"
    assert sig.indicator_key == "population.total"


async def test_extreme_percentile_top():
    await _seed_places_and_values()
    result = await detect_insights(
        DetectInsightsInput(place_id="ltla24:E0000009", indicator_keys=["population.total"]),
        get_engine(),
    )
    sig = next(s for s in result.signals if s.kind == "extreme_percentile")
    assert sig.severity == "extreme"


async def test_no_signals_for_median_place():
    await _seed_places_and_values()
    # Place 4 (180k) is near the middle — should not trigger extreme_percentile
    result = await detect_insights(
        DetectInsightsInput(place_id="ltla24:E0000004", indicator_keys=["population.total"]),
        get_engine(),
    )
    extreme = [s for s in result.signals if s.kind == "extreme_percentile"]
    assert len(extreme) == 0


async def test_empty_signals_when_no_data():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM geography.place"))
    result = await detect_insights(
        DetectInsightsInput(place_id="ltla24:NONEXISTENT"),
        engine,
    )
    assert result.signals == []
```

**Step 2: Run tests to verify failure**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest tests/test_detect_insights.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soundings.tools.detect_insights'`

**Step 3: Write the implementation**

```python
# server/soundings/tools/detect_insights.py
"""detect_insights tool — deterministic SQL-driven insight detector.

Returns InsightSignals for:
- extreme_percentile: value in top/bottom decile of same-type peers
- peer_divergence: value >1 SD from same-type median
- trend_reversal: most recent slope sign differs from prior 3-point average

All detection is pure SQL against data.indicator_value and data.trend_point.
No live API calls. Deterministic against a given data snapshot.
"""

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

TOOL_NAME = "detect_insights"
TOOL_DESCRIPTION = (
    "Detect statistically notable signals for a place: extreme percentiles "
    "(top/bottom decile vs peers), peer divergence (>1 SD from median), and "
    "trend reversals. Returns deterministic signals for Claude to narrate over."
)


class InsightSignal(BaseModel):
    indicator_key: str
    severity: str  # "extreme" | "notable"
    kind: str  # "extreme_percentile" | "peer_divergence" | "trend_reversal"
    evidence_payload: dict[str, float | str | None] = Field(default_factory=dict)


class DetectInsightsInput(BaseModel):
    place_id: str
    indicator_keys: list[str] | None = None  # None = all indicators


class DetectInsightsOutput(BaseModel):
    signals: list[InsightSignal] = Field(default_factory=list)


def tool_spec() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": DetectInsightsInput.model_json_schema(),
        "output_schema": DetectInsightsOutput.model_json_schema(),
    }


_EXTREME_PERCENTILE_SQL = """
WITH place_type AS (
    SELECT type FROM geography.place WHERE id = :place_id
),
peer_values AS (
    SELECT iv.place_id, iv.indicator_key, iv.value
    FROM data.indicator_value iv
    JOIN geography.place p ON p.id = iv.place_id
    WHERE p.type = (SELECT type FROM place_type)
      AND iv.value IS NOT NULL
      AND (CAST(:keys AS text[]) IS NULL OR iv.indicator_key = ANY(:keys))
),
ranked AS (
    SELECT
        pv.indicator_key,
        pv.value,
        pv.place_id,
        PERCENT_RANK() OVER (PARTITION BY pv.indicator_key ORDER BY pv.value) AS pct,
        COUNT(*) OVER (PARTITION BY pv.indicator_key) AS n_peers
    FROM peer_values pv
)
SELECT indicator_key, value, pct, n_peers
FROM ranked
WHERE place_id = :place_id
"""

_PEER_DIVERGENCE_SQL = """
WITH place_type AS (
    SELECT type FROM geography.place WHERE id = :place_id
),
peer_stats AS (
    SELECT
        iv.indicator_key,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY iv.value) AS median_val,
        STDDEV_POP(iv.value) AS std_dev
    FROM data.indicator_value iv
    JOIN geography.place p ON p.id = iv.place_id
    WHERE p.type = (SELECT type FROM place_type)
      AND iv.value IS NOT NULL
      AND (CAST(:keys AS text[]) IS NULL OR iv.indicator_key = ANY(:keys))
    GROUP BY iv.indicator_key
),
place_vals AS (
    SELECT iv.indicator_key, iv.value
    FROM data.indicator_value iv
    WHERE iv.place_id = :place_id AND iv.value IS NOT NULL
)
SELECT ps.indicator_key, pv.value, ps.median_val, ps.std_dev
FROM place_vals pv
JOIN peer_stats ps ON ps.indicator_key = pv.indicator_key
WHERE ps.std_dev IS NOT NULL AND ps.std_dev > 0
  AND ABS(pv.value - ps.median_val) > ps.std_dev
"""

_TREND_REVERSAL_SQL = """
WITH place_type AS (
    SELECT type FROM geography.place WHERE id = :place_id
),
ranked_points AS (
    SELECT
        tp.indicator_key,
        tp.period,
        tp.value,
        ROW_NUMBER() OVER (PARTITION BY tp.indicator_key ORDER BY tp.period DESC) AS rn
    FROM data.trend_point tp
    WHERE tp.place_id = :place_id
      AND (CAST(:keys AS text[]) IS NULL OR tp.indicator_key = ANY(:keys))
),
recent AS (
    SELECT indicator_key,
        MAX(CASE WHEN rn = 1 THEN value END) AS latest_val,
        MAX(CASE WHEN rn = 1 THEN period END) AS latest_period,
        MAX(CASE WHEN rn = 2 THEN value END) AS prev_val,
        MAX(CASE WHEN rn = 2 THEN period END) AS prev_period,
        AVG(CASE WHEN rn IN (3, 4, 5) THEN value END) AS prior_avg
    FROM ranked_points
    WHERE rn <= 5
    GROUP BY indicator_key
    HAVING COUNT(*) >= 5
)
SELECT indicator_key, latest_val, latest_period, prev_val, prior_avg
FROM recent
WHERE latest_val IS NOT NULL AND prev_val IS NOT NULL AND prior_avg IS NOT NULL
  AND (
    (latest_val - prev_val > 0 AND prev_val - prior_avg < 0)
    OR
    (latest_val - prev_val < 0 AND prev_val - prior_avg > 0)
  )
"""


async def detect_insights(
    input: DetectInsightsInput, engine: AsyncEngine
) -> DetectInsightsOutput:
    signals: list[InsightSignal] = []
    keys = input.indicator_keys if input.indicator_keys else None

    # 1. Extreme percentiles
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(_EXTREME_PERCENTILE_SQL),
                {"place_id": input.place_id, "keys": keys},
            )
        ).all()
    for r in rows:
        pct = float(r.pct) * 100 if r.pct is not None else None
        if pct is None:
            continue
        severity = "extreme" if (pct <= 5 or pct >= 95) else "notable"
        if pct <= 10 or pct >= 90:
            signals.append(InsightSignal(
                indicator_key=r.indicator_key,
                severity=severity,
                kind="extreme_percentile",
                evidence_payload={
                    "percentile": round(pct, 1),
                    "value": float(r.value) if r.value is not None else None,
                    "n_peers": int(r.n_peers),
                },
            ))

    # 2. Peer divergence
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(_PEER_DIVERGENCE_SQL),
                {"place_id": input.place_id, "keys": keys},
            )
        ).all()
    for r in rows:
        signals.append(InsightSignal(
            indicator_key=r.indicator_key,
            severity="notable",
            kind="peer_divergence",
            evidence_payload={
                "value": float(r.value) if r.value is not None else None,
                "median": float(r.median_val) if r.median_val is not None else None,
                "std_dev": float(r.std_dev) if r.std_dev is not None else None,
            },
        ))

    # 3. Trend reversals
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(_TREND_REVERSAL_SQL),
                {"place_id": input.place_id, "keys": keys},
            )
        ).all()
    for r in rows:
        signals.append(InsightSignal(
            indicator_key=r.indicator_key,
            severity="notable",
            kind="trend_reversal",
            evidence_payload={
                "latest_value": float(r.latest_val) if r.latest_val is not None else None,
                "latest_period": str(r.latest_period) if r.latest_period is not None else None,
                "prior_average": float(r.prior_avg) if r.prior_avg is not None else None,
            },
        ))

    return DetectInsightsOutput(signals=signals)
```

**Step 4: Run tests to verify pass**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest tests/test_detect_insights.py -v`
Expected: 4 passed

**Step 5: Lint + type check**

Run: `cd server && uv run ruff check soundings/tools/detect_insights.py && uv run mypy soundings/tools/detect_insights.py`
Expected: clean

**Step 6: Commit**

```bash
git add server/soundings/tools/detect_insights.py server/tests/test_detect_insights.py
git commit -m "feat(ask): add detect_insights tool with SQL-driven percentile, divergence, and reversal signals"
```

---

### Task 5: Wire `detect_insights` into the dispatcher

**Objective:** Add detect_insights to the ToolDispatcher so the orchestrator can route Claude calls to it.

**Files:**
- Modify: `server/soundings/ask/dispatcher.py`
- Modify: `server/tests/test_ask_dispatcher.py`

**Step 1: Add failing test**

Append to `server/tests/test_ask_dispatcher.py`:

```python
async def test_dispatcher_can_dispatch_detect_insights():
    """detect_insights should be in the dispatcher's handler map."""
    state = _make_state()
    d = ToolDispatcher(state)
    assert "detect_insights" in d._handlers
```

**Step 2: Run test to verify failure**

Run: `cd server && uv run pytest tests/test_ask_dispatcher.py::test_dispatcher_can_dispatch_detect_insights -v`
Expected: FAIL — KeyError or assertion error

**Step 3: Implement**

In `server/soundings/ask/dispatcher.py`, add import:

```python
from soundings.tools.detect_insights import (
    DetectInsightsInput,
    detect_insights,
    tool_spec as detect_insights_spec,
)
```

Add to `tool_specs()` return list (before compose_answer):

```python
            detect_insights_spec(),
```

Add to `_handlers` dict:

```python
            "detect_insights": self._handle_detect_insights,
```

Add handler method:

```python
    async def _handle_detect_insights(self, args: dict[str, Any]) -> dict[str, Any]:
        result = await detect_insights(
            DetectInsightsInput(**args), self._state.engine
        )
        return result.model_dump(mode="json")
```

**Step 4: Run tests to verify pass**

Run: `cd server && uv run pytest tests/test_ask_dispatcher.py -v`
Expected: 5 passed

**Step 5: Lint + type check**

Run: `cd server && uv run ruff check soundings/ask/dispatcher.py && uv run mypy soundings/ask/dispatcher.py`
Expected: clean

**Step 6: Commit**

```bash
git add server/soundings/ask/dispatcher.py server/tests/test_ask_dispatcher.py
git commit -m "feat(ask): wire detect_insights into tool dispatcher"
```

---

### Task 6: Create system prompt builder (`ask/prompts.py`)

**Objective:** Build the system prompt with mode-specific emphasis and optional pinned place context.

**Files:**
- Create: `server/soundings/ask/prompts.py`
- Create: `server/tests/test_ask_prompts.py`

**Step 1: Write failing tests**

```python
# server/tests/test_ask_prompts.py
"""Unit tests for the system prompt builder."""
from soundings.ask.prompts import SystemPromptBuilder, AskMode


def test_open_mode_prompt_contains_general_guidance():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "Soundings" in prompt
    assert "tool" in prompt.lower()
    assert "compose_answer" in prompt


def test_summary_mode_emphasises_breadth():
    builder = SystemPromptBuilder(mode="summary")
    prompt = builder.build()
    assert "breadth" in prompt.lower() or "summary" in prompt.lower()


def test_compare_mode_emphasises_comparison():
    builder = SystemPromptBuilder(mode="compare")
    prompt = builder.build()
    assert "compare" in prompt.lower()
    assert "percentile" in prompt.lower()


def test_insight_mode_emphasises_signals():
    builder = SystemPromptBuilder(mode="insight")
    prompt = builder.build()
    assert "insight" in prompt.lower() or "surprising" in prompt.lower()
    assert "detect_insights" in prompt


def test_pinned_place_included_in_prompt():
    builder = SystemPromptBuilder(mode="open", place_name="Stockton-on-Tees", place_id="ltla24:E06000004")
    prompt = builder.build()
    assert "Stockton-on-Tees" in prompt
    assert "ltla24:E06000004" in prompt


def test_scope_guardrail_present():
    builder = SystemPromptBuilder(mode="open")
    prompt = builder.build()
    assert "population" in prompt
    assert "health" in prompt
    assert "cannot help" in prompt.lower() or "out of scope" in prompt.lower()


def test_invalid_mode_raises():
    import pytest
    with pytest.raises(ValueError):
        SystemPromptBuilder(mode="bad")  # type: ignore[arg-type]
```

**Step 2: Run tests to verify failure**

Run: `cd server && uv run pytest tests/test_ask_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# server/soundings/ask/prompts.py
"""System prompt builder for the ask orchestrator.

Modes are knobs on the system prompt — they all use the same /v1/ask
endpoint and the same answer renderer. The mode is a per-request hint;
the model is allowed to flex if the user's free text expresses a different
intent.
"""

from typing import Literal

AskMode = Literal["open", "summary", "compare", "insight"]

_MODE_EMPHASIS: dict[AskMode, str] = {
    "open": (
        "You are a generalist. Pick whichever tools fit the question. "
        "Be thorough but concise."
    ),
    "summary": (
        "Emphasise breadth across all available domains. Aim for one "
        "indicator card per major domain. Close each section with a short "
        "narrative paragraph."
    ),
    "compare": (
        "Always include at least one compare-chart block. Ground your "
        "narrative in percentile framing. Resolve peers via compare_places' "
        "same-type peer universe."
    ),
    "insight": (
        "Lead with the deterministic signals from detect_insights. "
        "Include one insight-callout per signal, ordered by severity. "
        "Your narrative explains the 'so what' for each signal."
    ),
}

_SCOPE_DESCRIPTION = """\
Soundings answers questions about UK places using open data. The available
domains are: population, deprivation, economy, health, education, housing,
crime, and civil society. You have these tools:

- find_place: resolve a place name or postcode to a canonical geography ID
- get_place_profile: baseline summary of a place across domains
- get_indicators: fetch specific indicators for a place
- compare_places: compare a place against peers (percentile, rank, absolute, rate)
- get_trend: fetch a time series for an indicator at a place
- find_organisations_in_place: find charities and civil society orgs in a place
- get_civil_society_profile: summary of the charity sector in a place
- detect_insights: deterministic statistical signals (extreme percentiles, peer divergence, trend reversals)
- compose_answer: terminal — compose the final answer from typed blocks

If a question is out of scope (weather, news, opinions, advice, anything not
answerable by the tools above), respond with a single text block explaining
what Soundings can help with and suggest the user try summarising a place or
comparing two.
"""

_BLOCK_GUIDANCE = """\
Block types for compose_answer:
- text: markdown prose (use for narrative, explanations, context)
- indicator-card: a single indicator value for a place
- trend-chart: a time-series chart for one indicator at one place
- compare-chart: a bar chart comparing an indicator across 2-10 places
- organisations: a list of civil society organisations in a place
- insight-callout: a severity-coloured callout for a notable signal

Limits: max 20 blocks total, max 6 visual blocks (everything except text).
Always interleave text with visual blocks — never put all charts at the end.
"""


class SystemPromptBuilder:
    def __init__(
        self,
        mode: AskMode = "open",
        place_name: str | None = None,
        place_id: str | None = None,
    ) -> None:
        if mode not in _MODE_EMPHASIS:
            raise ValueError(f"Invalid mode: {mode}")
        self.mode = mode
        self.place_name = place_name
        self.place_id = place_id

    def build(self) -> str:
        parts: list[str] = [
            "You are Soundings, an AI assistant that answers questions about UK places using open data.",
            "",
            _SCOPE_DESCRIPTION,
            "",
            f"Mode: {self.mode}. {_MODE_EMPHASIS[self.mode]}",
            "",
            _BLOCK_GUIDANCE,
        ]
        if self.place_name and self.place_id:
            parts.extend([
                "",
                f"The user is asking about {self.place_name} (ID: {self.place_id}). "
                f"Use this place_id directly unless the user asks about a different place.",
            ])
        return "\n".join(parts)
```

**Step 4: Run tests to verify pass**

Run: `cd server && uv run pytest tests/test_ask_prompts.py -v`
Expected: 7 passed

**Step 5: Lint + type check**

Run: `cd server && uv run ruff check soundings/ask/prompts.py && uv run mypy soundings/ask/prompts.py`
Expected: clean

**Step 6: Commit**

```bash
git add server/soundings/ask/prompts.py server/tests/test_ask_prompts.py
git commit -m "feat(ask): add system prompt builder with mode-specific emphasis"
```

---

### Task 7: Create AskOrchestrator (`ask/orchestrator.py`)

**Objective:** Run the Claude tool-use loop. Stream SSE events. Enforce max iterations and timeout. Resolve compose_answer blocks against the fetch cache.

**Files:**
- Create: `server/soundings/ask/orchestrator.py`
- Create: `server/tests/test_ask_orchestrator.py`

**Step 1: Write failing tests**

```python
# server/tests/test_ask_orchestrator.py
"""Unit tests for the AskOrchestrator with mocked Claude responses."""
import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soundings.ask.blocks import ComposeAnswerArgs, TextBlock


class FakeDispatcher:
    def __init__(self):
        self.tool_specs_return = [
            {"name": "find_place", "description": "d", "input_schema": {}},
            {"name": "compose_answer", "description": "d", "input_schema": {}},
        ]

    def tool_specs(self):
        return self.tool_specs_return

    def is_terminal_tool(self, name):
        return name == "compose_answer"

    async def dispatch(self, name, args):
        if name == "find_place":
            return {"matches": [{"id": "ltla24:E06000004", "name": "Stockton-on-Tees", "type": "ltla24", "confidence": 0.95}]}
        if name == "compose_answer":
            return ComposeAnswerArgs(blocks=[TextBlock(type="text", markdown="Done!")]).model_dump(mode="json")
        return {}

    @property
    def sources(self):
        return []


class FakeAnthropicResponse:
    """Simulates an Anthropic API response with tool_use blocks."""
    def __init__(self, content_blocks, stop_reason="tool_use"):
        self.content = content_blocks
        self.stop_reason = stop_reason

    @property
    def text(self):
        return ""


def _make_tool_use_block(name, input_dict):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_dict
    return block


def _make_text_block(text="thinking..."):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


class FakeStream:
    """Simulates Anthropic SDK streaming with events."""
    def __init__(self, responses):
        self._responses = responses
        self._idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._responses):
            raise StopAsyncIteration
        resp = self._responses[self._idx]
        self._idx += 1
        return resp


@pytest.fixture
def fake_state():
    from types import SimpleNamespace
    return SimpleNamespace(
        geography_service=AsyncMock(),
        orchestrator=AsyncMock(),
        engine=MagicMock(),
    )


async def test_orchestrator_streams_status_events(fake_state):
    """Status events should fire for each tool call."""
    events = []

    def callback(event):
        events.append(event)
        return asyncio.Future()  # no-op

    dispatcher = FakeDispatcher()
    prompt_builder = MagicMock()
    prompt_builder.build.return_value = "system prompt"

    # Claude first calls find_place, then compose_answer
    stream_responses = [
        FakeAnthropicResponse([_make_text_block("Looking up..."), _make_tool_use_block("find_place", {"query": "Stockton"})]),
        FakeAnthropicResponse([_make_tool_use_block("compose_answer", {"blocks": [{"type": "text", "markdown": "Done!"}]})], stop_reason="end_turn"),
    ]

    with patch("soundings.ask.orchestrator.get_anthropic_client") as mock_client:
        mock_client.return_value.messages = MagicMock()
        mock_client.return_value.messages.stream.return_value = FakeStream(stream_responses)

        from soundings.ask.orchestrator import AskOrchestrator
        orch = AskOrchestrator(
            dispatcher=dispatcher,
            prompt_builder=prompt_builder,
            api_key="fake-key",
            model="claude-sonnet-4-20250514",
        )
        await orch.run("Tell me about Stockton", callback=lambda e: events.append(e))

    # Should have status events for tool calls
    status_events = [e for e in events if e.get("type") == "status"]
    assert len(status_events) >= 1

    # Should have a done event
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1

    # Should have block events from compose_answer
    block_events = [e for e in events if e.get("type") == "block"]
    assert len(block_events) >= 1


async def test_orchestrator_respects_max_iterations(fake_state):
    """Should stop and emit error after max iterations."""
    events = []

    dispatcher = FakeDispatcher()
    prompt_builder = MagicMock()
    prompt_builder.build.return_value = "system prompt"

    # Claude keeps calling find_place forever
    infinite_responses = [
        FakeAnthropicResponse([_make_tool_use_block("find_place", {"query": "Stockton"})])
        for _ in range(20)
    ]

    with patch("soundings.ask.orchestrator.get_anthropic_client") as mock_client:
        mock_client.return_value.messages = MagicMock()
        mock_client.return_value.messages.stream.return_value = FakeStream(infinite_responses)

        from soundings.ask.orchestrator import AskOrchestrator
        orch = AskOrchestrator(
            dispatcher=dispatcher,
            prompt_builder=prompt_builder,
            api_key="fake-key",
            model="claude-sonnet-4-20250514",
            max_iterations=3,
        )
        await orch.run("Stockton", callback=lambda e: events.append(e))

    error_events = [e for e in events if e.get("type") == "error"]
    assert len(error_events) == 1
    assert "iteration" in error_events[0]["message"].lower() or "max" in error_events[0]["message"].lower()


async def test_orchestrator_emits_sources(fake_state):
    """Should emit a sources event before done."""
    events = []

    dispatcher = FakeDispatcher()
    # Add sources to the dispatcher
    from soundings.contracts.source_ref import SourceRef
    from datetime import datetime, UTC
    dispatcher._sources_list = [SourceRef(
        source_id="ons.mid_year_estimates",
        source_label="ONS Mid-Year Estimates",
        publisher="ONS",
        retrieved_at=datetime.now(tz=UTC),
        cache_status="cached",
        licence="OGL",
    )]

    # Override sources property
    type(dispatcher).sources = property(lambda self: getattr(self, '_sources_list', []))

    prompt_builder = MagicMock()
    prompt_builder.build.return_value = "system prompt"

    stream_responses = [
        FakeAnthropicResponse([_make_tool_use_block("compose_answer", {"blocks": [{"type": "text", "markdown": "Done!"}]})], stop_reason="end_turn"),
    ]

    with patch("soundings.ask.orchestrator.get_anthropic_client") as mock_client:
        mock_client.return_value.messages = MagicMock()
        mock_client.return_value.messages.stream.return_value = FakeStream(stream_responses)

        from soundings.ask.orchestrator import AskOrchestrator
        orch = AskOrchestrator(
            dispatcher=dispatcher,
            prompt_builder=prompt_builder,
            api_key="fake-key",
            model="claude-sonnet-4-20250514",
        )
        await orch.run("Stockton", callback=lambda e: events.append(e))

    sources_events = [e for e in events if e.get("type") == "sources"]
    assert len(sources_events) == 1
```

**Step 2: Run tests to verify failure**

Run: `cd server && uv run pytest tests/test_ask_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the implementation**

```python
# server/soundings/ask/orchestrator.py
"""AskOrchestrator — runs the Claude tool-use loop and streams SSE events.

The loop:
1. Send the system prompt + user question to Claude with tool definitions.
2. Claude responds with tool_use blocks.
3. Dispatch each tool_use to the in-process handler via ToolDispatcher.
4. Feed results back to Claude as tool_result blocks.
5. Repeat until Claude calls compose_answer (terminal) or max iterations.
6. Stream SSE events: status (per tool call), block (from compose_answer),
   sources (deduped SourceRefs), done.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from anthropic import Anthropic

from soundings.ask.blocks import ComposeAnswerArgs
from soundings.ask.dispatcher import ToolDispatcher
from soundings.ask.prompts import AskMode, SystemPromptBuilder

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 12
MAX_TOKENS_OUTPUT = 8192
MAX_TOKENS_INPUT = 20480
REQUEST_TIMEOUT_SECONDS = 45

SSECallback = Callable[[dict[str, Any]], Awaitable[None] | None]


def get_anthropic_client(api_key: str) -> Anthropic:
    return Anthropic(api_key=api_key)


class AskOrchestrator:
    def __init__(
        self,
        *,
        dispatcher: ToolDispatcher,
        prompt_builder: SystemPromptBuilder,
        api_key: str,
        model: str,
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        self._dispatcher = dispatcher
        self._prompt_builder = prompt_builder
        self._api_key = api_key
        self._model = model
        self._max_iterations = max_iterations

    async def run(
        self,
        query: str,
        callback: SSECallback,
    ) -> None:
        """Run the tool-use loop, streaming events via callback."""
        client = get_anthropic_client(self._api_key)
        system_prompt = self._prompt_builder.build()
        tool_specs = self._dispatcher.tool_specs()

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": query}
        ]

        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                await self._loop(client, system_prompt, tool_specs, messages, callback)
        except TimeoutError:
            await _emit(callback, {"type": "error", "message": "Request timed out"})
        except Exception as e:
            logger.exception("Ask orchestrator error")
            await _emit(callback, {"type": "error", "message": str(e)})

    async def _loop(
        self,
        client: Anthropic,
        system_prompt: str,
        tool_specs: list[dict[str, object]],
        messages: list[dict[str, Any]],
        callback: SSECallback,
    ) -> None:
        for iteration in range(self._max_iterations):
            # Call Claude with streaming
            stream = client.messages.stream(
                model=self._model,
                max_tokens=MAX_TOKENS_OUTPUT,
                system=system_prompt,
                tools=tool_specs,
                messages=messages,
            )

            collected_text = ""
            tool_use_blocks: list[dict[str, Any]] = []

            async with stream as s:
                async for event in s:
                    if event.type == "text":
                        collected_text += event.text
                    elif event.type == "tool_use":
                        tool_use_blocks.append({
                            "id": event.id,
                            "name": event.name,
                            "input": event.input,
                        })

            # If Claude made tool calls, dispatch them
            if tool_use_blocks:
                # Append assistant message with tool calls
                assistant_content: list[dict[str, Any]] = []
                if collected_text:
                    assistant_content.append({"type": "text", "text": collected_text})
                for tb in tool_use_blocks:
                    assistant_content.append(tb)
                messages.append({"role": "assistant", "content": assistant_content})

                # Dispatch each tool call
                tool_results: list[dict[str, Any]] = []
                for tb in tool_use_blocks:
                    name = tb["name"]
                    tool_input = tb["input"]

                    if self._dispatcher.is_terminal_tool(name):
                        # compose_answer — parse blocks and emit
                        parsed = self._dispatcher._parse_compose_answer(tool_input)
                        for block in parsed.blocks:
                            await _emit(callback, {"type": "block", "block": block.model_dump(mode="json")})

                        # Emit sources
                        sources = [s.model_dump(mode="json") for s in self._dispatcher.sources]
                        await _emit(callback, {"type": "sources", "sources": sources})
                        await _emit(callback, {"type": "done"})
                        return

                    # Non-terminal tool — dispatch and emit status
                    await _emit(callback, {"type": "status", "message": f"Calling {name}…"})
                    try:
                        result = await self._dispatcher.dispatch(name, tool_input)
                    except Exception as e:
                        result = {"error": str(e)}

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tb["id"],
                        "content": str(result),
                    })

                messages.append({"role": "user", "content": tool_results})
                continue

            # No tool calls — Claude is done talking (shouldn't normally happen
            # without compose_answer, but handle gracefully)
            if collected_text:
                await _emit(callback, {"type": "block", "block": {"type": "text", "markdown": collected_text}})
            await _emit(callback, {"type": "sources", "sources": [s.model_dump(mode="json") for s in self._dispatcher.sources]})
            await _emit(callback, {"type": "done"})
            return

        # Max iterations exceeded
        await _emit(callback, {
            "type": "error",
            "message": f"Exceeded max iterations ({self._max_iterations})",
        })


async def _emit(callback: SSECallback, event: dict[str, Any]) -> None:
    result = callback(event)
    if asyncio.iscoroutine(result):
        await result
```

**Step 4: Run tests to verify pass**

Run: `cd server && uv run pytest tests/test_ask_orchestrator.py -v`
Expected: 3 passed

**Step 5: Lint + type check**

Run: `cd server && uv run ruff check soundings/ask/orchestrator.py && uv run mypy soundings/ask/orchestrator.py`
Expected: clean

**Step 6: Commit**

```bash
git add server/soundings/ask/orchestrator.py server/tests/test_ask_orchestrator.py
git commit -m "feat(ask): add AskOrchestrator with Claude tool-use loop and SSE streaming"
```

---

### Task 8: Create `/v1/ask` HTTP route

**Objective:** FastAPI endpoint that validates input, opens an SSE response, runs the orchestrator.

**Files:**
- Create: `server/soundings/http/ask.py`
- Create: `server/tests/test_ask_route.py`

**Step 1: Write failing tests**

```python
# server/tests/test_ask_route.py
"""Integration tests for the /v1/ask endpoint."""
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration


async def test_ask_returns_400_on_empty_query():
    from soundings.app import app
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/v1/ask", json={"query": ""})
    assert response.status_code == 400


async def test_ask_returns_422_on_bad_mode():
    from soundings.app import app
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/v1/ask", json={"query": "Stockton", "mode": "bad"})
    assert response.status_code == 422


async def test_ask_returns_sse_stream_with_mocked_claude():
    """With a mocked Claude, should get SSE events."""
    from unittest.mock import patch, MagicMock, AsyncMock
    from soundings.app import app

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            with patch("soundings.ask.orchestrator.get_anthropic_client") as mock:
                mock.return_value.messages = MagicMock()
                # Minimal streaming response that calls compose_answer
                mock_stream = AsyncMock()
                mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
                mock_stream.__aexit__ = AsyncMock(return_value=None)
                mock_stream.__aiter__ = MagicMock(return_value=iter([]))
                mock.return_value.messages.stream.return_value = mock_stream

                response = await ac.post(
                    "/v1/ask",
                    json={"query": "Tell me about Stockton", "mode": "summary"},
                )
    # Should be SSE content type
    assert "text/event-stream" in response.headers.get("content-type", "")
```

**Step 2: Run tests to verify failure**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest tests/test_ask_route.py -v`
Expected: FAIL — no `/v1/ask` route

**Step 3: Write the implementation**

```python
# server/soundings/http/ask.py
"""HTTP route for /v1/ask — the natural-language ask interface.

POST /v1/ask with {query, place_id?, mode?} → SSE stream of events.
"""

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from soundings.ask.dispatcher import ToolDispatcher
from soundings.ask.orchestrator import AskOrchestrator
from soundings.ask.prompts import AskMode, SystemPromptBuilder
from soundings.core.config import get_settings

router = APIRouter(prefix="/v1")


class AskInput(BaseModel):
    query: str
    place_id: str | None = None
    mode: AskMode = "open"


@router.post("/ask")
async def ask(input: AskInput, request: Request) -> StreamingResponse:
    if not input.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")

    # Build place context if a place_id is provided
    place_name: str | None = None
    if input.place_id:
        from sqlalchemy import text
        async with request.app.state.engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT name FROM geography.place WHERE id = :id"),
                    {"id": input.place_id},
                )
            ).first()
        if row:
            place_name = row.name

    prompt_builder = SystemPromptBuilder(
        mode=input.mode,
        place_name=place_name,
        place_id=input.place_id,
    )

    dispatcher = ToolDispatcher(request.app.state)

    orchestrator = AskOrchestrator(
        dispatcher=dispatcher,
        prompt_builder=prompt_builder,
        api_key=settings.anthropic_api_key,
        model=settings.ask_model,
    )

    async def event_stream():
        queue: list[str] = []

        async def callback(event: dict[str, Any]) -> None:
            queue.append(json.dumps(event))

        # Run the orchestrator
        await orchestrator.run(input.query, callback)

        # Flush all events as SSE
        for data in queue:
            yield f"data: {data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

**Step 4: Run tests to verify pass**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest tests/test_ask_route.py -v`
Expected: 3 passed

**Step 5: Lint + type check**

Run: `cd server && uv run ruff check soundings/http/ask.py && uv run mypy soundings/http/ask.py`
Expected: clean

**Step 6: Commit**

```bash
git add server/soundings/http/ask.py server/tests/test_ask_route.py
git commit -m "feat(ask): add /v1/ask SSE endpoint with input validation"
```

---

### Task 9: Wire `/v1/ask` route and extend capture middleware

**Objective:** Register the ask route in app.py and extend the capture middleware path prefix to include `/v1/ask`.

**Files:**
- Modify: `server/soundings/app.py`
- Modify: `server/soundings/capture/middleware.py`

**Step 1: Modify app.py**

In `server/soundings/app.py`, add import:

```python
from soundings.http.ask import router as ask_router
```

Add after `app.include_router(tools_router)`:

```python
app.include_router(ask_router)
```

**Step 2: Modify capture middleware**

In `server/soundings/capture/middleware.py`, change the path check to also capture `/v1/ask`:

Change:
```python
if scope["type"] != "http" or not scope["path"].startswith(TOOLS_PATH_PREFIX):
```
To:
```python
if scope["type"] != "http" or not (scope["path"].startswith(TOOLS_PATH_PREFIX) or scope["path"] == "/v1/ask"):
```

Update `_extract_tool_name` to handle `/v1/ask`:

```python
def _extract_tool_name(path: str) -> str:
    if path == "/v1/ask":
        return "ask"
    return path[len(TOOLS_PATH_PREFIX) :].split("/", 1)[0]
```

**Step 3: Verify existing tests still pass**

Run: `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m "not live" -v --tb=short`
Expected: existing tests still pass (may have the 4 pre-existing failures)

**Step 4: Lint + type check**

Run: `cd server && uv run ruff check soundings/app.py soundings/capture/middleware.py && uv run mypy soundings/app.py soundings/capture/middleware.py`
Expected: clean

**Step 5: Commit**

```bash
git add server/soundings/app.py server/soundings/capture/middleware.py
git commit -m "feat(ask): wire /v1/ask route into app and extend capture middleware"
```

---

### Task 10: Register `ask` in MCP server

**Objective:** Expose the ask orchestrator as an MCP tool so MCP clients can also use it.

**Files:**
- Modify: `server/soundings/mcp/server.py`

**Step 1: Add ask tool registration**

In `server/soundings/mcp/server.py`, add at the end of `build_mcp_server`, before `return mcp`:

```python
    @mcp.tool(name="ask")
    async def _ask(query: str, place_id: str | None = None, mode: str = "open") -> dict[str, Any]:
        """Ask a natural-language question about a UK place."""
        if state is None:
            raise RuntimeError("MCP ask invoked without app state")
        from soundings.ask.dispatcher import ToolDispatcher
        from soundings.ask.orchestrator import AskOrchestrator
        from soundings.ask.prompts import SystemPromptBuilder
        from soundings.core.config import get_settings

        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")

        # Resolve place name if place_id provided
        place_name = None
        if place_id:
            from sqlalchemy import text
            async with state.engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT name FROM geography.place WHERE id = :id"),
                        {"id": place_id},
                    )
                ).first()
            if row:
                place_name = row.name

        prompt_builder = SystemPromptBuilder(mode=mode, place_name=place_name, place_id=place_id)
        dispatcher = ToolDispatcher(state)
        orchestrator = AskOrchestrator(
            dispatcher=dispatcher,
            prompt_builder=prompt_builder,
            api_key=settings.anthropic_api_key,
            model=settings.ask_model,
        )

        blocks: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []

        async def callback(event: dict[str, Any]) -> None:
            if event["type"] == "block":
                blocks.append(event["block"])
            elif event["type"] == "sources":
                sources = event["sources"]

        await orchestrator.run(query, callback)
        return {"blocks": blocks, "sources": sources}
```

**Step 2: Verify tests pass**

Run: `cd server && uv run pytest -m "not live" --tb=short`
Expected: no new failures

**Step 3: Lint + type check**

Run: `cd server && uv run ruff check soundings/mcp/server.py && uv run mypy soundings/mcp/server.py`
Expected: clean

**Step 4: Commit**

```bash
git add server/soundings/mcp/server.py
git commit -m "feat(ask): register ask tool in MCP server"
```

---

### Task 11: Add live test for the ask endpoint

**Objective:** One real-Claude call with `mode="summary"` for a seeded LTLA. Nightly only.

**Files:**
- Create: `server/tests/test_ask_live.py`

**Step 1: Write the test**

```python
# server/tests/test_ask_live.py
"""Live test for the /v1/ask endpoint — real Claude call.

Nightly only. Requires ANTHROPIC_API_KEY in env.
"""
import json

import pytest
from httpx import ASGITransport, AsyncClient

from soundings.app import app
from soundings.db.engine import get_engine
from sqlalchemy import text
import uuid
from datetime import UTC, datetime, timedelta

pytestmark = [pytest.mark.live, pytest.mark.integration]


async def _seed_stockton():
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.loader_run"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        run = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:E06000004', 'ltla24', 'E06000004', 'Stockton-on-Tees')"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO data.loader_run (id, source_id, started_at, finished_at, status, rows_written) "
                "VALUES (:id, 'ons.mid_year_estimates', :s, :f, 'ok', 1)"
            ),
            {"id": run, "s": now - timedelta(minutes=5), "f": now},
        )
        await conn.execute(
            text(
                "INSERT INTO data.indicator_value "
                "(place_id, indicator_key, period, value, source_id, retrieved_at, caveats) "
                "VALUES ('ltla24:E06000004', 'population.total', '2024', 200000, 'ons.mid_year_estimates', :ret, '[]'::jsonb)"
            ),
            {"ret": now},
        )


async def test_ask_summary_returns_text_and_indicator_blocks():
    await _seed_stockton()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/v1/ask",
                json={
                    "query": "Summarise Stockton-on-Tees",
                    "place_id": "ltla24:E06000004",
                    "mode": "summary",
                },
            )
    assert response.status_code == 200
    # Parse SSE events
    events = []
    for line in response.text.split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))

    # Should have at least one text block
    block_events = [e for e in events if e.get("type") == "block"]
    text_blocks = [e for e in block_events if e["block"]["type"] == "text"]
    assert len(text_blocks) >= 1

    # Should have a done event
    assert any(e.get("type") == "done" for e in events)
```

**Step 2: Verify it's collected by the live marker**

Run: `cd server && uv run pytest tests/test_ask_live.py --collect-only`
Expected: collected, marked as live + integration

**Step 3: Commit**

```bash
git add server/tests/test_ask_live.py
git commit -m "test(ask): add live test for /v1/ask with real Claude call"
```

---

## Slice B — UI

### Task 12: Create SSE client (`answer_stream.ts`)

**Objective:** TypeScript SSE client that parses events and emits an ordered list of typed blocks.

**Files:**
- Create: `ui/src/lib/answer_stream.ts`
- Create: `ui/tests/answer_stream.test.ts`

**Step 1: Write failing tests**

```typescript
// ui/tests/answer_stream.test.ts
import { describe, it, expect } from "vitest";
import { parseSSEStream, AskEvent } from "../src/lib/answer_stream";

describe("answer_stream", () => {
  it("parses status event", () => {
    const line = `data: {"type":"status","message":"Looking up Stockton…"}`;
    const events = parseSSEStream(line);
    expect(events).toHaveLength(1);
    expect(events[0].type).toBe("status");
    expect((events[0] as any).message).toBe("Looking up Stockton…");
  });

  it("parses block event", () => {
    const line = `data: {"type":"block","block":{"type":"text","markdown":"Hello"}}`;
    const events = parseSSEStream(line);
    expect(events[0].type).toBe("block");
  });

  it("parses done event", () => {
    const line = `data: {"type":"done"}`;
    const events = parseSSEStream(line);
    expect(events[0].type).toBe("done");
  });

  it("parses error event", () => {
    const line = `data: {"type":"error","message":"Something went wrong"}`;
    const events = parseSSEStream(line);
    expect(events[0].type).toBe("error");
  });

  it("handles multiple events", () => {
    const lines = [
      `data: {"type":"status","message":"Working…"}`,
      `data: {"type":"block","block":{"type":"text","markdown":"Hi"}}`,
      `data: {"type":"done"}`,
    ].join("\n\n");
    const events = parseSSEStream(lines);
    expect(events).toHaveLength(3);
    expect(events[0].type).toBe("status");
    expect(events[1].type).toBe("block");
    expect(events[2].type).toBe("done");
  });

  it("skips empty lines", () => {
    const lines = "\n\ndata: {\"type\":\"done\"}\n\n";
    const events = parseSSEStream(lines);
    expect(events).toHaveLength(1);
  });
});
```

**Step 2: Run tests to verify failure**

Run: `cd ui && npx vitest run tests/answer_stream.test.ts`
Expected: FAIL — module not found

**Step 3: Write the implementation**

```typescript
// ui/src/lib/answer_stream.ts
/** SSE client for the /v1/ask endpoint. Parses server-sent events into typed objects. */

export type AskEvent =
  | { type: "status"; message: string }
  | { type: "block"; block: AnswerBlock }
  | { type: "sources"; sources: SourceRef[] }
  | { type: "done" }
  | { type: "error"; message: string };

export interface AnswerBlock {
  type: "text" | "indicator-card" | "trend-chart" | "compare-chart" | "organisations" | "insight-callout";
  [key: string]: unknown;
}

export interface SourceRef {
  source_id: string;
  source_label: string;
  publisher: string;
  retrieved_at: string;
  cache_status: string;
  licence: string;
}

/** Parse a raw SSE text blob into a list of AskEvents. */
export function parseSSEStream(raw: string): AskEvent[] {
  const events: AskEvent[] = [];
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || !trimmed.startsWith("data: ")) continue;
    try {
      const json = JSON.parse(trimmed.slice(6));
      events.push(json as AskEvent);
    } catch {
      // skip malformed lines
    }
  }
  return events;
}

/** Open an SSE connection to /v1/ask and call onEvent for each parsed event. */
export async function streamAsk(
  url: string,
  body: { query: string; place_id?: string; mode?: string },
  onEvent: (event: AskEvent) => void,
): Promise<void> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    onEvent({ type: "error", message: `HTTP ${response.status}` });
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    onEvent({ type: "error", message: "No response body" });
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // Split on double newlines (SSE event boundary)
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const events = parseSSEStream(part);
      for (const event of events) {
        onEvent(event);
      }
    }
  }
  // Flush remaining buffer
  if (buffer.trim()) {
    for (const event of parseSSEStream(buffer)) {
      onEvent(event);
    }
  }
}
```

**Step 4: Run tests to verify pass**

Run: `cd ui && npx vitest run tests/answer_stream.test.ts`
Expected: 6 passed

**Step 5: Commit**

```bash
git add ui/src/lib/answer_stream.ts ui/tests/answer_stream.test.ts
git commit -m "feat(ask): add SSE client for parsing /v1/ask events"
```

---

### Task 13: Create AskBox component

**Objective:** Text input + 3 mode chips (Summary / Compare / Surprise me). Submits to `/ask?q=…&place_id=…&mode=…`. Reused on `/` and `/place/[id]`.

**Files:**
- Create: `ui/src/components/AskBox.astro`

**Step 1: Write the component**

```astro
---
// ui/src/components/AskBox.astro
interface Props {
  placeId?: string;
  placeName?: string;
}

const { placeId, placeName } = Astro.props;

const modes = [
  { id: "summary", label: "Summary", placeholder: `Summarise ${placeName ?? "a place"}` },
  { id: "compare", label: "Compare", placeholder: `How does ${placeName ?? "a place"} compare to its peers?` },
  { id: "insight", label: "Surprise me", placeholder: `What's surprising about ${placeName ?? "a place"}?` },
];
---

<div class="ask-box" data-place-id={placeId ?? ""}>
  <form class="ask-form" action="/ask" method="get">
    <input type="hidden" name="place_id" value={placeId ?? ""} />
    <label>
      <span class="ask-label">Ask a question about a place</span>
      <input
        type="text"
        name="q"
        class="ask-input"
        placeholder="What do you want to know about a place?"
        autocomplete="off"
        required
      />
    </label>
    <button type="submit" class="ask-submit">Ask</button>
    <div class="mode-chips">
      {modes.map((m) => (
        <button
          type="button"
          class="mode-chip"
          data-mode={m.id}
          data-placeholder={m.placeholder}
        >
          {m.label}
        </button>
      ))}
    </div>
  </form>
</div>

<style>
  .ask-box {
    margin: var(--space-xl) 0;
  }
  .ask-form {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-md);
    align-items: end;
  }
  .ask-form label {
    flex: 1;
    min-width: 250px;
    display: flex;
    flex-direction: column;
    gap: var(--space-sm);
  }
  .ask-label {
    font-weight: var(--font-weight-medium);
    color: var(--color-primary);
  }
  .ask-input {
    padding: var(--space-md);
    font-size: var(--font-size-lg);
  }
  .ask-submit {
    padding: var(--space-md) var(--space-xl);
    height: fit-content;
  }
  .mode-chips {
    display: flex;
    gap: var(--space-sm);
    width: 100%;
    margin-top: var(--space-sm);
  }
  .mode-chip {
    padding: var(--space-xs) var(--space-md);
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
    background: var(--color-surface);
    cursor: pointer;
    font-size: var(--font-size-sm);
    transition: background 0.15s;
  }
  .mode-chip:hover {
    background: var(--color-primary);
    color: white;
  }
  .mode-chip.active {
    background: var(--color-primary);
    color: white;
    border-color: var(--color-primary);
  }
</style>

<script>
  const chips = document.querySelectorAll<HTMLButtonElement>(".mode-chip");
  const input = document.querySelector<HTMLInputElement>(".ask-input");
  const form = document.querySelector<HTMLFormElement>(".ask-form");
  let selectedMode = "open";

  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      chips.forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      selectedMode = chip.dataset.mode ?? "open";
      const placeholder = chip.dataset.placeholder;
      if (placeholder && input) {
        input.placeholder = placeholder;
      }
      // If place_id is set, submit immediately
      const placeId = document.querySelector<HTMLInputElement>('input[name="place_id"]')?.value;
      if (placeId && input) {
        input.value = chip.dataset.placeholder ?? "";
        form?.submit();
      }
    });
  });
</script>
```

**Step 2: Commit**

```bash
git add ui/src/components/AskBox.astro
git commit -m "feat(ask): add AskBox component with mode chips"
```

---

### Task 14: Create `/ask` page

**Objective:** Reads URL params, renders SSR shell, client-only island streams answer blocks.

**Files:**
- Create: `ui/src/pages/ask.astro`

**Step 1: Write the page**

```astro
---
// ui/src/pages/ask.astro
import Base from "../layouts/Base.astro";

export const prerender = false;

const url = new URL(Astro.request.url);
const query = url.searchParams.get("q") ?? "";
const placeId = url.searchParams.get("place_id") ?? "";
const mode = url.searchParams.get("mode") ?? "open";
---

<Base title={query ? `Soundings — ${query}` : "Ask Soundings"}>
  <section class="ask-page" data-query={query} data-place-id={placeId} data-mode={mode}>
    <h1>{query || "Ask a question"}</h1>
    <div id="answer-surface" class="answer-surface">
      <p class="loading">Thinking…</p>
    </div>
    <div id="answer-sources" class="answer-sources"></div>
  </section>

  <style>
    .ask-page h1 {
      font-size: var(--font-size-xl);
      margin-bottom: var(--space-lg);
    }
    .answer-surface {
      min-height: 200px;
    }
    .loading {
      color: var(--color-muted);
      font-style: italic;
    }
    .answer-block {
      margin: var(--space-lg) 0;
    }
    .answer-block.text {
      line-height: 1.6;
    }
    .answer-block.text h2 {
      font-size: var(--font-size-lg);
      margin: var(--space-md) 0 var(--space-sm);
    }
    .status-msg {
      color: var(--color-muted);
      font-size: var(--font-size-sm);
      padding: var(--space-xs) 0;
    }
    .insight-callout {
      padding: var(--space-md);
      border-radius: var(--radius);
      margin: var(--space-md) 0;
    }
    .insight-callout.extreme {
      background: #fef3c7;
      border-left: 4px solid #f59e0b;
    }
    .insight-callout.notable {
      background: #dbeafe;
      border-left: 4px solid #3b82f6;
    }
    .insight-callout .headline {
      font-weight: var(--font-weight-medium);
      margin-bottom: var(--space-xs);
    }
    .insight-callout .evidence {
      font-size: var(--font-size-sm);
      color: var(--color-text-light);
    }
    .answer-sources {
      margin-top: var(--space-xl);
      padding-top: var(--space-lg);
      border-top: 1px solid var(--color-border-light);
      font-size: var(--font-size-sm);
      color: var(--color-muted);
    }
  </style>

  <script>
    const page = document.querySelector(".ask-page");
    const query = page?.getAttribute("data-query") ?? "";
    const placeId = page?.getAttribute("data-place-id") ?? "";
    const mode = page?.getAttribute("data-mode") ?? "open";
    const surface = document.getElementById("answer-surface");
    const sourcesEl = document.getElementById("answer-sources");

    if (query && surface) {
      surface.innerHTML = '<p class="loading">Thinking…</p>';
      const apiBase = (import.meta as any).env?.SOUNDINGS_API_BASE ?? "http://localhost:8001";

      import("../lib/answer_stream").then(async ({ streamAsk }) => {
        const blocks: HTMLElement[] = [];
        let statusEl: HTMLElement | null = null;

        await streamAsk(`${apiBase}/v1/ask`, {
          query,
          place_id: placeId || undefined,
          mode,
        }, (event) => {
          if (event.type === "status") {
            if (!statusEl) {
              statusEl = document.createElement("p");
              statusEl.className = "status-msg";
              surface.appendChild(statusEl);
            }
            statusEl.textContent = event.message;
          } else if (event.type === "block") {
            // Remove loading + status
            surface.querySelector(".loading")?.remove();
            if (statusEl) {
              statusEl.remove();
              statusEl = null;
            }
            const el = renderBlock(event.block);
            if (el) surface.appendChild(el);
          } else if (event.type === "sources") {
            if (sourcesEl && event.sources?.length) {
              sourcesEl.innerHTML = "<h3>Sources</h3>" + event.sources
                .map((s: any) => `<p>${s.source_label} — ${s.publisher} (${s.licence})</p>`)
                .join("");
            }
          } else if (event.type === "done") {
            surface.querySelector(".loading")?.remove();
            if (statusEl) statusEl.remove();
          } else if (event.type === "error") {
            surface.querySelector(".loading")?.remove();
            surface.innerHTML += `<p class="error">Couldn't reach the model — ${event.message}. <a href="#" onclick="location.reload(); return false;">Retry</a></p>`;
          }
        });
      });
    }

    function renderBlock(block: any): HTMLElement | null {
      const div = document.createElement("div");
      div.className = `answer-block ${block.type}`;

      switch (block.type) {
        case "text": {
          // Basic markdown: bold, headings, paragraphs
          const html = block.markdown
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
            .replace(/^## (.+)$/gm, "<h2>$1</h2>")
            .replace(/\n/g, "<br>");
          div.innerHTML = html;
          return div;
        }
        case "insight-callout": {
          div.classList.add("insight-callout", block.severity);
          const headline = document.createElement("div");
          headline.className = "headline";
          headline.textContent = block.headline;
          const evidence = document.createElement("div");
          evidence.className = "evidence";
          evidence.textContent = block.evidence;
          div.appendChild(headline);
          div.appendChild(evidence);
          return div;
        }
        case "indicator-card":
        case "trend-chart":
        case "compare-chart":
        case "organisations": {
          // For v1, render a placeholder. Full chart integration is a
          // follow-up that requires fetching the data and reusing the
          // existing Observable Plot components client-side.
          const label = document.createElement("p");
          label.className = "block-placeholder";
          label.textContent = `[${block.type}: ${block.indicator_key ?? block.place_id ?? ""}]`;
          div.appendChild(label);
          return div;
        }
        default:
          return null;
      }
    }
  </script>
</Base>
```

**Step 2: Commit**

```bash
git add ui/src/pages/ask.astro
git commit -m "feat(ask): add /ask page with SSE streaming and block rendering"
```

---

### Task 15: Add AskBox to homepage and place page

**Objective:** Integrate AskBox into the existing pages so users discover the ask interface.

**Files:**
- Modify: `ui/src/pages/index.astro`
- Modify: `ui/src/pages/place/[id].astro`

**Step 1: Add to homepage**

In `ui/src/pages/index.astro`, add import after existing imports:

```astro
import AskBox from "../components/AskBox.astro";
```

Add after the search form `</form>` and before the error/matches sections:

```astro
  <AskBox />
  <hr class="divider" />
```

Add to the `<style>`:

```css
  .divider {
    border: none;
    border-top: 1px solid var(--color-border-light);
    margin: var(--space-xl) 0;
  }
```

**Step 2: Add to place page**

In `ui/src/pages/place/[id].astro`, add import:

```astro
import AskBox from "../../components/AskBox.astro";
```

Add after the `<Base>` opening tag, before the first content section:

```astro
  <AskBox placeId={profile?.place.id ?? placeId} placeName={profile?.place.name ?? placeId} />
```

**Step 3: Verify pages compile**

Run: `cd ui && npm run build`
Expected: build succeeds

**Step 4: Commit**

```bash
git add ui/src/pages/index.astro ui/src/pages/place/[id].astro
git commit -m "feat(ask): integrate AskBox into homepage and place page"
```

---

### Task 16: Add Vitest tests for UI components

**Objective:** Test the answer_stream, AskBox behaviour, and block rendering.

**Files:**
- Create: `ui/tests/ask_box.test.ts`
- Modify: `ui/tests/answer_stream.test.ts` (already exists from Task 12)

**Step 1: Write AskBox tests**

```typescript
// ui/tests/ask_box.test.ts
import { describe, it, expect } from "vitest";
import { parseSSEStream } from "../src/lib/answer_stream";

describe("ask integration", () => {
  it("mode chips produce correct query params", () => {
    // Simulate the URL that would be constructed
    const url = new URL("http://localhost:4321/ask");
    url.searchParams.set("q", "How does Stockton compare to its peers?");
    url.searchParams.set("place_id", "ltla24:E06000004");
    url.searchParams.set("mode", "compare");
    expect(url.searchParams.get("mode")).toBe("compare");
    expect(url.searchParams.get("q")).toContain("compare");
  });

  it("open mode has no preset query", () => {
    const url = new URL("http://localhost:4321/ask");
    url.searchParams.set("q", "What's the poverty rate in Stockton?");
    url.searchParams.set("mode", "open");
    expect(url.searchParams.get("mode")).toBe("open");
  });
});
```

**Step 2: Run tests**

Run: `cd ui && npx vitest run`
Expected: all pass

**Step 3: Commit**

```bash
git add ui/tests/
git commit -m "test(ask): add Vitest tests for ask integration"
```

---

### Task 17: Create browser smoke runbook

**Objective:** Manual runbook that gates the phase tag, same pattern as Phase 3/4 runbooks.

**Files:**
- Create: `docs/runbook-ask-smoke.md`

**Step 1: Write the runbook**

```markdown
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
```

**Step 2: Commit**

```bash
git add docs/runbook-ask-smoke.md
git commit -m "docs(ask): add browser smoke runbook for ask interface"
```

---

### Task 18: Update STATE.md and PLAN.md

**Objective:** Reflect the ask interface work in the project tracking files.

**Files:**
- Modify: `STATE.md`
- Modify: `PLAN.md`
- Modify: `CLAUDE.md` (state & progress section)

**Step 1: Update tracking files**

In `STATE.md`, add a new row to the component status table:

```
| **Ask interface — /v1/ask + /ask page** | ✅ Phase 6 (ask) | Claude tool-use loop over existing tools. SSE streaming. 4 modes. detect_insights SQL detector. |
```

Update the "WE ARE HERE" marker and status line.

In `PLAN.md`, mark the ask interface task as complete:

```
- [x] Ask interface — natural-language /v1/ask endpoint with Claude tool-use loop, SSE streaming, detect_insights, and Astro /ask page.
```

In `CLAUDE.md`, update the State & Progress section.

**Step 2: Commit**

```bash
git add STATE.md PLAN.md CLAUDE.md
git commit -m "docs: update tracking files for ask interface completion"
```

---

## Summary

**Slice A (Tasks 1-11):** Server foundation — config, block schema, dispatcher, insight detector, prompt builder, orchestrator, HTTP route, capture integration, MCP registration, live test.

**Slice B (Tasks 12-18):** UI — SSE client, AskBox, /ask page, block rendering, integration into existing pages, tests, runbook, tracking file updates.

**Total: 18 tasks, ~3-4 days of focused TDD work.**

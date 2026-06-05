# Civil Society Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "list 10 charities" experience on `/place/[id]` with a richer civil society profile that tells the user the size and shape of the third sector in their place — total active charities, income distribution, median/mean size, and registration-cohort trend — backed by a new `get_civil_society_profile` tool and a structured UI panel with charts.

**Architecture:** A new orchestrator method computes the profile via deterministic SQL against `data.organisation` + `data.organisation_operates_in` + `geography.place_hierarchy`. To make the analysis possible the CC bulk loader is extended to capture `latest_income`, `date_of_registration` and `date_of_removal` in the existing `data.organisation.raw` JSONB. The new tool is exposed on both the HTTP and MCP transports following the established pattern. The UI mounts a `<CivilSocietyPanel>` on the place page with Plot-based SVG charts (income buckets bar, registration trend line), replacing today's `<OrganisationsSection>`. Funder rollup, geographic map, and the natural-language ask interface are deliberately deferred (see "Out of scope" below).

**Tech Stack:** Python 3.12 / FastAPI / Pydantic / SQLAlchemy (asyncpg) / pytest+pytest-asyncio (server); Astro 4 SSR / TypeScript / `@observablehq/plot` + linkedom SSR polyfill (UI).

---

## Out of scope (slice 2 / 3, separate plans)

- **Funders active in the area** — needs either a 360G bulk loader populating `data.grant_record`, or a sample-based rollup strategy. Either way, ≥1 day of new design + loader work. Not in this plan.
- **Map of organisation locations** — needs a new UI mapping component (we have none) and a registered-vs-operates decision.
- **Structured classifications by theme / support area** — needs the second CC bulk file `publicextract.charity_classification.zip` and a code → human-label mapping.
- **Natural-language ask interface (`/ask`)** — separate spec at `docs/superpowers/specs/2026-05-31-ask-interface-design.md`. Once slice 1 ships its tool, the ask orchestrator gets one more building block.

## Existing files this plan touches (reference)

- `server/soundings/adapters/charity_commission/client.py` — bulk client; yields per-charity dicts.
- `server/soundings/adapters/charity_commission/loader.py:208-230` — `_build_org_rows`; stores yielded dict into `data.organisation.raw` verbatim, so capturing more fields in the client transparently widens the persisted JSONB.
- `server/soundings/orchestration/orchestrator.py:552-760` — existing `find_organisations_in_place` pattern; new method `compute_civil_society_profile` lives alongside it.
- `server/soundings/http/tools.py` — HTTP routes; mirror the existing `POST /v1/tools/find_organisations_in_place` registration.
- `server/soundings/mcp/server.py` — MCP tool registration; mirror existing handlers.
- `server/soundings/contracts/` — Pydantic response models.
- `ui/src/lib/api.ts` / `ui/src/lib/types.ts` — UI client + types.
- `ui/src/lib/chart.ts` — Observable Plot SSR renderers (`renderSparkline`, `renderCompareBars`); add two more.
- `ui/src/pages/place/[id].astro` — currently mounts `<OrganisationsSection>`; swap for `<CivilSocietyPanel>`.
- `ui/src/components/OrganisationsSection.astro` — deleted at end of plan.

## Files this plan creates

- `server/soundings/contracts/civil_society.py` — `CivilSocietyProfile`, `IncomeBucket`, `RegistrationCohort` Pydantic models.
- `server/tests/test_civil_society_contracts.py` — contract roundtrip + bucket invariants.
- `server/tests/test_cc_client_extra_fields.py` — bulk client yields the new fields.
- `server/tests/fixtures/charity_commission/sample_with_extras.tsv` — minimal CC bulk fixture.
- `server/tests/test_orchestrator_civil_society.py` — SQL aggregation correctness against a seeded DB.
- `server/soundings/tools/get_civil_society_profile.py` — tool input/output spec.
- `server/tests/test_tool_get_civil_society_profile_spec.py` — tool spec round-trips.
- `server/tests/test_http_civil_society.py` — HTTP route end-to-end.
- `ui/src/components/CivilSocietyPanel.astro` — main panel.
- `ui/src/components/IncomeBucketsChart.astro` — Plot bar chart wrapper.
- `ui/src/components/RegistrationTrendChart.astro` — Plot line chart wrapper.

## Verification commands (used throughout)

- Unit + integration suite against the test DB:
  `cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest <args>`
- Lint + type:
  `cd /Users/tomcwxyz/code/dataforaction-tom/soundings && make lint type`

The test DB must exist (`make test-db-create` documented in the Makefile). Postgres must be up (`make up` or just `docker start soundings-postgres-1`). All `pytestmark = pytest.mark.integration` tests need the running Postgres.

---

# Block 1: extend the CC loader to capture income + dates

The bulk client currently yields five fields. Three more are needed for analysis: `latest_income`, `date_of_registration`, `date_of_removal`. The loader stores the whole dict in `raw` unchanged, so this is a client-only change.

### Task 1: Add a minimal CC bulk fixture with the new columns

**Files:**
- Create: `server/tests/fixtures/charity_commission/sample_with_extras.tsv`

- [ ] **Step 1: Create the fixture**

The real bulk file is tab-delimited with the columns CC publishes. We only need a 3-row file with the columns the client reads. CC's actual header includes ~30 columns; only the ones the code touches need real values.

Write `server/tests/fixtures/charity_commission/sample_with_extras.tsv` with content:

```
registered_charity_number	linked_charity_number	charity_name	charity_registration_status	charity_contact_postcode	charity_activities	latest_income	date_of_registration	date_of_removal
1010101	0	ALPHA TRUST	Registered	DH1 1AA	Helping local schoolchildren.	150000	2010-04-12
1020202	0	BETA FUND	Registered	DH2 2BB	Community arts and culture.	7500	1998-11-30
1030303	0	GAMMA SOCIETY	Removed	DH3 3CC	Older people support.	950000	2002-06-01	2024-03-15
```

(One active small charity, one active medium charity, one removed large one. The removed row must round-trip through the client filter and be dropped.)

- [ ] **Step 2: Commit**

```bash
git add server/tests/fixtures/charity_commission/sample_with_extras.tsv
git commit -m "test(cc): minimal bulk fixture with income + date columns"
```

### Task 2: Failing test — bulk client yields income + dates

**Files:**
- Create: `server/tests/test_cc_client_extra_fields.py`

- [ ] **Step 1: Write the failing test**

The bulk client streams from a ZIP read from HTTP. We bypass HTTP by zipping the fixture inline and constructing the client with a `MockTransport`. The current client yields `{registration_number, name, postcode, status, classification}`. The new test asserts the additional keys.

Write `server/tests/test_cc_client_extra_fields.py`:

```python
"""The bulk client must capture the income + date columns that the
civil society profile aggregates depend on. Failing here means the
analytical SQL has nothing to chew on."""

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from soundings.adapters.charity_commission.client import (
    CC_CHARITY_BULK_URL,
    CHARITY_TXT,
    CharityCommissionBulkClient,
)

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).parent / "fixtures" / "charity_commission" / "sample_with_extras.tsv"


def _zip_fixture() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(CHARITY_TXT, FIXTURE.read_bytes())
    return buf.getvalue()


async def test_client_yields_income_and_dates_for_active_rows() -> None:
    zipped = _zip_fixture()

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CC_CHARITY_BULK_URL
        return httpx.Response(200, content=zipped)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = CharityCommissionBulkClient(http_client=http)
        rows = [row async for row in client.iter_active_charities()]

    # Removed row dropped, two active rows survive.
    assert len(rows) == 2
    by_reg = {r["registration_number"]: r for r in rows}

    alpha = by_reg["1010101"]
    assert alpha["latest_income"] == 150000.0
    assert alpha["date_of_registration"] == "2010-04-12"
    assert alpha["date_of_removal"] is None

    beta = by_reg["1020202"]
    assert beta["latest_income"] == 7500.0
    assert beta["date_of_registration"] == "1998-11-30"
    assert beta["date_of_removal"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
cd server && uv run pytest tests/test_cc_client_extra_fields.py -v
```
Expected: FAIL with `KeyError: 'latest_income'`.

### Task 3: Implement — bulk client captures the new fields

**Files:**
- Modify: `server/soundings/adapters/charity_commission/client.py:63-94`

- [ ] **Step 1: Update the yield dict**

Replace the body of `iter_active_charities` so it pulls and coerces the three new columns. The CSV reader returns strings; income coerces to `float`, blank dates coerce to `None`.

Edit `server/soundings/adapters/charity_commission/client.py`. Replace the existing `yield` block (lines ~86-94) with:

```python
                    yield {
                        "registration_number": reg,
                        "name": row.get("charity_name", "").strip(),
                        "postcode": row.get("charity_contact_postcode", "").strip(),
                        "status": "Registered",
                        "classification": _activities_to_classification(
                            row.get("charity_activities", "")
                        ),
                        "latest_income": _coerce_float(row.get("latest_income")),
                        "date_of_registration": _blank_to_none(
                            row.get("date_of_registration")
                        ),
                        "date_of_removal": _blank_to_none(
                            row.get("date_of_removal")
                        ),
                    }
```

Add two module-level helpers at the bottom of the file:

```python
def _coerce_float(raw: str | None) -> float | None:
    """CC bulk leaves `latest_income` blank for charities that haven't
    filed an annual return. Treat blank + non-numeric as None rather
    than 0.0, so downstream aggregates can exclude them cleanly."""
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _blank_to_none(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None
```

- [ ] **Step 2: Run test to verify it passes**

Run:
```
cd server && uv run pytest tests/test_cc_client_extra_fields.py -v
```
Expected: PASS, 1 test.

- [ ] **Step 3: Run the existing CC loader tests to confirm no regression**

The loader stores the dict as-is in `raw`, so existing tests should still pass — but they may assert specific JSONB shapes.

Run:
```
DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest tests/test_cc_loader.py tests/test_cc_indicator_aggregation.py -v
```
Expected: PASS. If any test asserts the exact `raw` shape, update it to use `>=` on key count or check specific keys.

- [ ] **Step 4: Commit**

```bash
git add server/soundings/adapters/charity_commission/client.py server/tests/test_cc_client_extra_fields.py
git commit -m "feat(cc): capture latest_income + date_of_registration + date_of_removal"
```

---

# Block 2: civil society profile contracts

A small Pydantic module describing the new tool's response. Pure Python; no DB.

### Task 4: Failing test — contract round-trip + invariants

**Files:**
- Create: `server/tests/test_civil_society_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
"""Contract round-trip + invariants for CivilSocietyProfile."""

import pytest

from soundings.contracts.civil_society import (
    CivilSocietyProfile,
    IncomeBucket,
    RegistrationCohort,
)
from soundings.contracts.source_ref import SourceRef


def _src() -> SourceRef:
    return SourceRef(
        source_id="charity_commission",
        source_label="Charity Commission for England and Wales",
        publisher="Charity Commission",
        retrieved_at="2026-06-02T10:00:00Z",
        cache_status="cached",
    )


def test_profile_round_trips_through_json() -> None:
    profile = CivilSocietyProfile(
        place_id="ltla24:E06000047",
        total_organisations=1034,
        with_reported_income=812,
        median_income=42000.0,
        mean_income=187000.0,
        income_buckets=[
            IncomeBucket(label="<10k", lower=0, upper=10_000, count=312),
            IncomeBucket(label="10k–100k", lower=10_000, upper=100_000, count=305),
            IncomeBucket(label="100k–1m", lower=100_000, upper=1_000_000, count=160),
            IncomeBucket(label="1m–10m", lower=1_000_000, upper=10_000_000, count=29),
            IncomeBucket(label="10m+", lower=10_000_000, upper=None, count=6),
        ],
        registration_cohort=[
            RegistrationCohort(year=2020, registered=22, removed=8, net=14),
            RegistrationCohort(year=2021, registered=29, removed=10, net=19),
        ],
        sources=[_src()],
        caveats=["Income from latest CC annual return; 222 charities have no return on file."],
        partial=False,
    )
    blob = profile.model_dump_json()
    rehydrated = CivilSocietyProfile.model_validate_json(blob)
    assert rehydrated == profile


def test_income_bucket_label_invariant() -> None:
    # The top bucket has no upper bound.
    bucket = IncomeBucket(label="10m+", lower=10_000_000, upper=None, count=6)
    assert bucket.upper is None

    # Lower-bound bucket has an upper.
    bucket2 = IncomeBucket(label="<10k", lower=0, upper=10_000, count=312)
    assert bucket2.upper == 10_000


def test_cohort_net_invariant() -> None:
    cohort = RegistrationCohort(year=2024, registered=10, removed=3, net=7)
    assert cohort.net == cohort.registered - cohort.removed
    with pytest.raises(ValueError):
        RegistrationCohort(year=2024, registered=10, removed=3, net=999)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
cd server && uv run pytest tests/test_civil_society_contracts.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'soundings.contracts.civil_society'`.

### Task 5: Implement contracts

**Files:**
- Create: `server/soundings/contracts/civil_society.py`

- [ ] **Step 1: Write the module**

```python
"""CivilSocietyProfile — response shape for `get_civil_society_profile`.

Aggregate view of registered charities operating in a place: total,
income distribution, median/mean size, and a registration-cohort
trend. Inputs come from `data.organisation` (CC bulk register) joined
to `data.organisation_operates_in`.
"""

from typing import Self

from pydantic import BaseModel, Field, model_validator

from soundings.contracts.source_ref import SourceRef


class IncomeBucket(BaseModel):
    label: str = Field(description="Human-readable bucket label, e.g. '<10k', '10k–100k'.")
    lower: float = Field(ge=0, description="Inclusive lower bound, GBP.")
    upper: float | None = Field(
        default=None,
        description="Exclusive upper bound, GBP. None for the open-ended top bucket.",
    )
    count: int = Field(ge=0)


class RegistrationCohort(BaseModel):
    year: int
    registered: int = Field(ge=0, description="Charities first registered in this year.")
    removed: int = Field(ge=0, description="Charities removed in this year.")
    net: int = Field(description="`registered` − `removed`.")

    @model_validator(mode="after")
    def _check_net(self) -> Self:
        if self.net != self.registered - self.removed:
            raise ValueError("net must equal registered - removed")
        return self


class CivilSocietyProfile(BaseModel):
    place_id: str
    total_organisations: int = Field(ge=0)
    with_reported_income: int = Field(
        ge=0,
        description=(
            "Subset of total_organisations that have a non-null `latest_income` on"
            " their CC return. Median/mean are computed over this subset."
        ),
    )
    median_income: float | None = Field(
        default=None, description="Median GBP of `latest_income` over reporting charities."
    )
    mean_income: float | None = Field(
        default=None, description="Mean GBP of `latest_income` over reporting charities."
    )
    income_buckets: list[IncomeBucket] = Field(default_factory=list)
    registration_cohort: list[RegistrationCohort] = Field(
        default_factory=list,
        description="One row per year, oldest first; window controlled by the orchestrator.",
    )
    sources: list[SourceRef] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    partial: bool = Field(default=False)
```

- [ ] **Step 2: Run test to verify it passes**

Run:
```
cd server && uv run pytest tests/test_civil_society_contracts.py -v
```
Expected: PASS, 3 tests.

- [ ] **Step 3: Commit**

```bash
git add server/soundings/contracts/civil_society.py server/tests/test_civil_society_contracts.py
git commit -m "feat(contracts): CivilSocietyProfile + IncomeBucket + RegistrationCohort"
```

---

# Block 3: orchestrator aggregation

The new method `compute_civil_society_profile(place_id)` queries the DB and returns a `CivilSocietyProfile`. Three SQL queries: total counts, income statistics + bucket breakdown, registration cohort. All three filter by `place_id` via `data.organisation_operates_in`.

### Task 6: Failing test — orchestrator returns correct aggregates

**Files:**
- Create: `server/tests/test_orchestrator_civil_society.py`

- [ ] **Step 1: Write the failing test**

```python
"""Integration test for IndicatorOrchestrator.compute_civil_society_profile.

Seeds a single LTLA with 6 charities spanning the income brackets, then
asserts the returned profile matches what hand-calculation says it
should be.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text

from soundings.adapters.registry import AdapterRegistry
from soundings.contracts.civil_society import CivilSocietyProfile
from soundings.db.engine import get_engine
from soundings.orchestration.orchestrator import IndicatorOrchestrator

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _cleanup() -> AsyncIterator[None]:
    engine = get_engine()
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.organisation_operates_in"))
        await conn.execute(text("DELETE FROM data.organisation"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place"))


async def _seed_six_charities() -> None:
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES (:id, 'ltla24', :c, 'Test Place')"
            ),
            {"id": "ltla24:T01", "c": "T01"},
        )
        # 6 charities with assorted incomes + registration years; one removed.
        rows = [
            ("c1", 5_000.0, "2018-01-01", None),
            ("c2", 9_000.0, "2019-04-04", None),
            ("c3", 75_000.0, "2020-06-15", None),
            ("c4", 800_000.0, "2021-09-20", None),
            ("c5", 4_000_000.0, "2015-02-10", None),
            ("c6", 12_000.0, "2010-03-12", "2022-08-01"),  # removed
        ]
        for cid, income, reg, removal in rows:
            raw = {
                "name": cid.upper(),
                "registration_number": cid,
                "latest_income": income,
                "date_of_registration": reg,
                "date_of_removal": removal,
            }
            await conn.execute(
                text(
                    "INSERT INTO data.organisation "
                    "(id, name, classification, source_id, retrieved_at, raw) "
                    "VALUES (:id, :n, ARRAY[]::varchar[], 'charity_commission', :r, "
                    " CAST(:raw AS jsonb))"
                ),
                {"id": cid, "n": cid.upper(), "r": now, "raw": __import__("json").dumps(raw)},
            )
            await conn.execute(
                text(
                    "INSERT INTO data.organisation_operates_in "
                    "(organisation_id, place_id) VALUES (:o, 'ltla24:T01')"
                ),
                {"o": cid},
            )


async def test_compute_civil_society_profile_aggregates_correctly() -> None:
    await _seed_six_charities()
    engine = get_engine()
    registry = AdapterRegistry()
    orch = IndicatorOrchestrator(engine=engine, registry=registry)

    profile: CivilSocietyProfile = await orch.compute_civil_society_profile(
        place_id="ltla24:T01"
    )

    # 6 total, all have income on file, one removed.
    assert profile.total_organisations == 6
    assert profile.with_reported_income == 6
    # Median of [5000, 9000, 12000, 75000, 800000, 4000000] = (12000 + 75000) / 2 = 43500.
    assert profile.median_income == pytest.approx(43_500.0)
    # Mean of the same = 816_833.33...
    assert profile.mean_income == pytest.approx((5_000 + 9_000 + 12_000 + 75_000 + 800_000 + 4_000_000) / 6)

    # Buckets: <10k (c1, c2) = 2; 10k–100k (c3, c6) = 2; 100k–1m (c4) = 1; 1m–10m (c5) = 1; 10m+ = 0.
    by_label = {b.label: b.count for b in profile.income_buckets}
    assert by_label["<10k"] == 2
    assert by_label["10k–100k"] == 2
    assert by_label["100k–1m"] == 1
    assert by_label["1m–10m"] == 1
    assert by_label["10m+"] == 0

    # Registration cohort: one row per distinct year present in the data,
    # net = registered - removed (so 2022 shows net=-1 from c6's removal).
    by_year = {c.year: c for c in profile.registration_cohort}
    assert by_year[2018].registered == 1
    assert by_year[2018].net == 1
    assert by_year[2022].registered == 0
    assert by_year[2022].removed == 1
    assert by_year[2022].net == -1
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest tests/test_orchestrator_civil_society.py -v
```
Expected: FAIL with `AttributeError: 'IndicatorOrchestrator' object has no attribute 'compute_civil_society_profile'`.

### Task 7: Implement the orchestrator method

**Files:**
- Modify: `server/soundings/orchestration/orchestrator.py` (append a new method on `IndicatorOrchestrator`)

- [ ] **Step 1: Add module-level bucket config near the existing constants**

Open `server/soundings/orchestration/orchestrator.py`. Near the existing top-of-file constants (around the `SERIES_BREAK_PREFIX = "series_break:"` line), add:

```python
# Fixed income brackets for the civil society profile. Picked to match
# the breakpoints reported in the CC sector overview (Annual Report on
# the Register). `upper=None` is the open-ended top bracket.
INCOME_BUCKETS: list[tuple[str, float, float | None]] = [
    ("<10k", 0.0, 10_000.0),
    ("10k–100k", 10_000.0, 100_000.0),
    ("100k–1m", 100_000.0, 1_000_000.0),
    ("1m–10m", 1_000_000.0, 10_000_000.0),
    ("10m+", 10_000_000.0, None),
]
```

- [ ] **Step 2: Add the imports needed**

At the top of the file, ensure these imports are present (add any missing):

```python
from datetime import UTC, datetime

from soundings.contracts.civil_society import (
    CivilSocietyProfile,
    IncomeBucket,
    RegistrationCohort,
)
from soundings.contracts.source_ref import SourceRef
```

- [ ] **Step 3: Append the method on `IndicatorOrchestrator`**

Add after the existing `_find_via_ftc` / grants helpers (anywhere on the class, but near the orgs methods is logical):

```python
    async def compute_civil_society_profile(self, place_id: str) -> CivilSocietyProfile:
        """Aggregate `data.organisation` rows operating in `place_id`
        into a civil society profile. Pure SQL — no upstream calls."""
        retrieved = datetime.now(tz=UTC)
        async with self._engine.connect() as conn:
            totals_row = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) AS total, "
                        "       COUNT((o.raw->>'latest_income')::numeric) AS with_income "
                        "FROM data.organisation_operates_in oi "
                        "JOIN data.organisation o ON o.id = oi.organisation_id "
                        "WHERE oi.place_id = :pid"
                    ),
                    {"pid": place_id},
                )
            ).first()
            total = int(totals_row.total) if totals_row else 0
            with_income = int(totals_row.with_income) if totals_row else 0

            stats_row = (
                await conn.execute(
                    text(
                        "SELECT AVG((o.raw->>'latest_income')::numeric) AS mean, "
                        "       percentile_cont(0.5) WITHIN GROUP ("
                        "         ORDER BY (o.raw->>'latest_income')::numeric"
                        "       ) AS median "
                        "FROM data.organisation_operates_in oi "
                        "JOIN data.organisation o ON o.id = oi.organisation_id "
                        "WHERE oi.place_id = :pid "
                        "  AND (o.raw->>'latest_income') IS NOT NULL"
                    ),
                    {"pid": place_id},
                )
            ).first()
            mean_income = float(stats_row.mean) if stats_row and stats_row.mean is not None else None
            median_income = (
                float(stats_row.median) if stats_row and stats_row.median is not None else None
            )

            # One COUNT per bucket via a single query. Build bucket clauses
            # inline (safe — labels/bounds are code-controlled).
            bucket_selects = []
            for idx, (label, lower, upper) in enumerate(INCOME_BUCKETS):
                if upper is None:
                    cond = (
                        f"(o.raw->>'latest_income')::numeric >= {lower}"
                    )
                else:
                    cond = (
                        f"(o.raw->>'latest_income')::numeric >= {lower} "
                        f"AND (o.raw->>'latest_income')::numeric < {upper}"
                    )
                bucket_selects.append(
                    f"COUNT(*) FILTER (WHERE {cond}) AS b{idx}"
                )
            buckets_row = (
                await conn.execute(
                    text(
                        f"SELECT {', '.join(bucket_selects)} "
                        "FROM data.organisation_operates_in oi "
                        "JOIN data.organisation o ON o.id = oi.organisation_id "
                        "WHERE oi.place_id = :pid "
                        "  AND (o.raw->>'latest_income') IS NOT NULL"
                    ),
                    {"pid": place_id},
                )
            ).first()
            income_buckets = [
                IncomeBucket(
                    label=label,
                    lower=lower,
                    upper=upper,
                    count=int(getattr(buckets_row, f"b{idx}", 0) or 0),
                )
                for idx, (label, lower, upper) in enumerate(INCOME_BUCKETS)
            ]

            cohort_rows = (
                await conn.execute(
                    text(
                        "WITH regs AS ( "
                        "  SELECT EXTRACT(YEAR FROM (o.raw->>'date_of_registration')::date)::int AS y, "
                        "         COUNT(*) AS n "
                        "  FROM data.organisation_operates_in oi "
                        "  JOIN data.organisation o ON o.id = oi.organisation_id "
                        "  WHERE oi.place_id = :pid "
                        "    AND (o.raw->>'date_of_registration') IS NOT NULL "
                        "  GROUP BY 1 "
                        "), rems AS ( "
                        "  SELECT EXTRACT(YEAR FROM (o.raw->>'date_of_removal')::date)::int AS y, "
                        "         COUNT(*) AS n "
                        "  FROM data.organisation_operates_in oi "
                        "  JOIN data.organisation o ON o.id = oi.organisation_id "
                        "  WHERE oi.place_id = :pid "
                        "    AND (o.raw->>'date_of_removal') IS NOT NULL "
                        "  GROUP BY 1 "
                        ") "
                        "SELECT COALESCE(regs.y, rems.y) AS year, "
                        "       COALESCE(regs.n, 0) AS registered, "
                        "       COALESCE(rems.n, 0) AS removed "
                        "FROM regs FULL OUTER JOIN rems ON regs.y = rems.y "
                        "ORDER BY year"
                    ),
                    {"pid": place_id},
                )
            ).all()
            cohort = [
                RegistrationCohort(
                    year=int(r.year),
                    registered=int(r.registered),
                    removed=int(r.removed),
                    net=int(r.registered) - int(r.removed),
                )
                for r in cohort_rows
            ]

        caveats: list[str] = []
        if total > 0 and with_income < total:
            caveats.append(
                f"{total - with_income} of {total} charities have no income on the latest CC return."
            )
        source = SourceRef(
            source_id="charity_commission",
            source_label="Charity Commission for England and Wales",
            publisher="Charity Commission",
            retrieved_at=retrieved,
            cache_status="cached",
        )
        return CivilSocietyProfile(
            place_id=place_id,
            total_organisations=total,
            with_reported_income=with_income,
            median_income=median_income,
            mean_income=mean_income,
            income_buckets=income_buckets,
            registration_cohort=cohort,
            sources=[source],
            caveats=caveats,
            partial=False,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```
DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest tests/test_orchestrator_civil_society.py -v
```
Expected: PASS, 1 test.

- [ ] **Step 5: Type check + lint**

Run:
```
cd /Users/tomcwxyz/code/dataforaction-tom/soundings && make lint type
```
Expected: all checks pass, no mypy errors.

- [ ] **Step 6: Commit**

```bash
git add server/soundings/orchestration/orchestrator.py server/tests/test_orchestrator_civil_society.py
git commit -m "feat(orchestrator): compute_civil_society_profile aggregates"
```

---

# Block 4: tool spec + HTTP + MCP wiring

Mirrors the existing `find_organisations_in_place` pattern: a tool spec file, an HTTP route, an MCP registration, and tests for each.

### Task 8: Failing test — tool spec

**Files:**
- Create: `server/tests/test_tool_get_civil_society_profile_spec.py`

- [ ] **Step 1: Write the failing test**

Matches the existing per-tool spec test pattern (see `server/tests/test_tool_find_organisations_spec.py`).

```python
"""Tests for get_civil_society_profile tool spec."""

import pytest

from soundings.tools.get_civil_society_profile import (
    GetCivilSocietyProfileInput,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    tool_spec,
)


def test_tool_spec_has_expected_fields() -> None:
    spec = tool_spec()
    assert spec["name"] == TOOL_NAME
    assert spec["description"] == TOOL_DESCRIPTION
    assert "input_schema" in spec
    assert "output_schema" in spec


def test_input_validation_accepts_place_id() -> None:
    parsed = GetCivilSocietyProfileInput(place_id="ltla24:E06000047")
    assert parsed.place_id == "ltla24:E06000047"


def test_input_validation_rejects_missing_place_id() -> None:
    with pytest.raises(Exception):
        GetCivilSocietyProfileInput.model_validate({})
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
cd server && uv run pytest tests/test_tool_get_civil_society_profile_spec.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'soundings.tools.get_civil_society_profile'`.

### Task 9: Implement the tool spec

**Files:**
- Create: `server/soundings/tools/get_civil_society_profile.py`

- [ ] **Step 1: Look at the existing pattern to match it**

Open `server/soundings/tools/find_organisations_in_place.py` for the canonical pattern: module-level `TOOL_NAME` + `TOOL_DESCRIPTION` constants, an `Input` Pydantic class, and a `tool_spec()` function returning `{name, description, input_schema, output_schema}`. The `CivilSocietyProfile` contract is the output directly — no wrapper class needed (cf. `get_place_profile` which returns `PlaceProfile`).

- [ ] **Step 2: Write the new spec + handler**

```python
"""get_civil_society_profile tool — aggregate civil society profile for a place.

Returns total active charities, income distribution + median/mean,
and a registration-cohort series. Backed by `data.organisation` +
`data.organisation_operates_in` populated by the CC bulk loader.
"""

from typing import Any

from pydantic import BaseModel, Field

from soundings.contracts.civil_society import CivilSocietyProfile


class GetCivilSocietyProfileInput(BaseModel):
    place_id: str = Field(
        description=(
            "Canonical geography place ID (e.g. ltla24:E06000047). The"
            " profile is computed from charities whose registered address"
            " resolves to this place via `data.organisation_operates_in`."
        )
    )


TOOL_NAME = "get_civil_society_profile"
TOOL_DESCRIPTION = (
    "Aggregate civil society profile for a UK place — total registered "
    "charities, annual-income distribution (with median + mean), and a "
    "year-by-year registration cohort series. Coverage: England + Wales "
    "(via the Charity Commission bulk register)."
)


def tool_spec() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": GetCivilSocietyProfileInput.model_json_schema(),
        "output_schema": CivilSocietyProfile.model_json_schema(),
    }


async def get_civil_society_profile(
    input: GetCivilSocietyProfileInput,
    orchestrator: Any,
) -> CivilSocietyProfile:
    """Tool handler — delegates to the orchestrator method."""
    return await orchestrator.compute_civil_society_profile(place_id=input.place_id)
```

- [ ] **Step 3: Run test to verify it passes**

Run:
```
cd server && uv run pytest tests/test_tool_get_civil_society_profile_spec.py -v
```
Expected: PASS, 3 tests.

- [ ] **Step 4: Commit**

```bash
git add server/soundings/tools/get_civil_society_profile.py server/tests/test_tool_get_civil_society_profile_spec.py
git commit -m "feat(tools): get_civil_society_profile tool spec"
```

### Task 10: Failing test — HTTP route

**Files:**
- Create: `server/tests/test_http_civil_society.py`

- [ ] **Step 1: Write the failing test**

Mirror `server/tests/test_http_find_organisations.py` (or equivalent — find an existing HTTP test in `server/tests/test_http_*.py` for the import style). The test posts to `/v1/tools/get_civil_society_profile`, expects a 200, and checks the response shape.

```python
"""HTTP end-to-end for /v1/tools/get_civil_society_profile.

Uses ASGITransport + the FastAPI lifespan to spin the app up against a
seeded test DB."""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import text

from soundings.app import app
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


async def _seed_minimum() -> None:
    engine = get_engine()
    now = datetime.now(tz=UTC)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.organisation_operates_in"))
        await conn.execute(text("DELETE FROM data.organisation"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place"))
        await conn.execute(
            text(
                "INSERT INTO geography.place (id, type, code, name) "
                "VALUES ('ltla24:H01', 'ltla24', 'H01', 'HTTP test place')"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO data.organisation "
                "(id, name, classification, source_id, retrieved_at, raw) "
                "VALUES ('h1', 'HTTP Trust', ARRAY[]::varchar[], 'charity_commission', :r, "
                " CAST(:raw AS jsonb))"
            ),
            {
                "r": now,
                "raw": '{"latest_income": 50000, "date_of_registration": "2019-05-01"}',
            },
        )
        await conn.execute(
            text(
                "INSERT INTO data.organisation_operates_in "
                "(organisation_id, place_id) VALUES ('h1', 'ltla24:H01')"
            )
        )


async def test_http_get_civil_society_profile_returns_aggregates() -> None:
    await _seed_minimum()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/tools/get_civil_society_profile",
                json={"place_id": "ltla24:H01"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["place_id"] == "ltla24:H01"
    assert body["total_organisations"] == 1
    assert body["with_reported_income"] == 1
    assert body["median_income"] == 50000.0
    assert body["income_buckets"][1]["label"] == "10k–100k"
    assert body["income_buckets"][1]["count"] == 1
    assert body["registration_cohort"][0]["year"] == 2019
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```
DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest tests/test_http_civil_society.py -v
```
Expected: FAIL with 404 on the `/v1/tools/get_civil_society_profile` POST.

### Task 11: Implement the HTTP route + MCP registration

**Files:**
- Modify: `server/soundings/http/tools.py`
- Modify: `server/soundings/mcp/server.py`

- [ ] **Step 1: Add the HTTP route**

Open `server/soundings/http/tools.py`. Find the `find_organisations_in_place` block (search for the string `find_organisations_in_place`). Follow its pattern: add an import alongside the existing tool imports, then a route decorator using the relative path (`/get_civil_society_profile` — the router already has the `/v1/tools` prefix).

Add to the import block near the top:

```python
from soundings.contracts.civil_society import CivilSocietyProfile
from soundings.tools.get_civil_society_profile import (
    GetCivilSocietyProfileInput,
    get_civil_society_profile,
)
```

Add the route, mirroring the existing `find_organisations_in_place` decorator (which uses `@router.post("/find_organisations_in_place", ...)`):

```python
@router.post("/get_civil_society_profile", response_model=CivilSocietyProfile)
async def http_get_civil_society_profile(
    input: GetCivilSocietyProfileInput,
    request: Request,
) -> CivilSocietyProfile:
    return await get_civil_society_profile(input, request.app.state.orchestrator)
```

- [ ] **Step 2: Add the MCP registration**

Open `server/soundings/mcp/server.py`. Find the `find_organisations_in_place` decorator (around line 119) — mirror its shape exactly.

Add to the imports near the top of the file:

```python
from soundings.tools.get_civil_society_profile import (
    GetCivilSocietyProfileInput,
    get_civil_society_profile,
)
```

Add the registration after the `find_organisations_in_place` one:

```python
    @mcp.tool(name="get_civil_society_profile")
    async def _get_civil_society_profile(place_id: str) -> dict[str, Any]:
        if state is None:
            raise RuntimeError(
                "MCP get_civil_society_profile invoked without app state"
            )
        result = await get_civil_society_profile(
            GetCivilSocietyProfileInput(place_id=place_id),
            state.orchestrator,
        )
        return result.model_dump(mode="json")
```

- [ ] **Step 4: Run HTTP test to verify it passes**

Run:
```
DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest tests/test_http_civil_society.py -v
```
Expected: PASS, 1 test.

- [ ] **Step 5: Run the broader server suite for regressions**

```
DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m "not live"
```
Expected: all previously-passing tests still pass.

- [ ] **Step 6: Type check + lint**

Run:
```
cd /Users/tomcwxyz/code/dataforaction-tom/soundings && make lint type
```
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add server/soundings/http/tools.py server/soundings/mcp/server.py server/tests/test_http_civil_society.py
git commit -m "feat(transport): wire get_civil_society_profile on HTTP + MCP"
```

---

# Block 5: UI — chart helpers, panel component, place page

### Task 12: Add the typed API client + types

**Files:**
- Modify: `ui/src/lib/types.ts`
- Modify: `ui/src/lib/api.ts`

- [ ] **Step 1: Add the TS types**

Append to `ui/src/lib/types.ts`:

```typescript
export interface IncomeBucket {
  label: string;
  lower: number;
  upper: number | null;
  count: number;
}

export interface RegistrationCohort {
  year: number;
  registered: number;
  removed: number;
  net: number;
}

export interface CivilSocietyProfile {
  place_id: string;
  total_organisations: number;
  with_reported_income: number;
  median_income: number | null;
  mean_income: number | null;
  income_buckets: IncomeBucket[];
  registration_cohort: RegistrationCohort[];
  sources: SourceRef[];
  caveats: string[];
  partial: boolean;
}
```

- [ ] **Step 2: Add the API method**

Append to `ui/src/lib/api.ts`:

```typescript
import type { CivilSocietyProfile } from "./types";

export async function getCivilSocietyProfile(
  placeId: string,
  opts: { cookieHeader?: string } = {},
): Promise<CivilSocietyProfile> {
  return postJSON<CivilSocietyProfile>(
    "/v1/tools/get_civil_society_profile",
    { place_id: placeId },
    { cookieHeader: opts.cookieHeader },
  );
}
```

(Adjust the import if `CivilSocietyProfile` is already imported into the existing import block at the top of the file — combine rather than duplicate.)

- [ ] **Step 3: Verify TypeScript**

Run:
```
cd ui && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add ui/src/lib/types.ts ui/src/lib/api.ts
git commit -m "feat(ui): typed client for get_civil_society_profile"
```

### Task 13: Income buckets chart + registration trend chart helpers

**Files:**
- Modify: `ui/src/lib/chart.ts`

- [ ] **Step 1: Add the two new renderers**

Append to `ui/src/lib/chart.ts` (after `renderCompareBars` / `renderSparkline`):

```typescript
import type { IncomeBucket, RegistrationCohort } from "./types";

export function renderIncomeBuckets(
  buckets: IncomeBucket[],
  opts: { width?: number; height?: number } = {},
): string {
  if (buckets.length === 0) return "";
  const width = opts.width ?? 480;
  const height = opts.height ?? 200;
  const node = Plot.plot({
    width,
    height,
    marginTop: 16,
    marginRight: 12,
    marginBottom: 36,
    marginLeft: 48,
    x: { label: "Annual income band", tickRotate: -15 },
    y: { grid: true, label: "Charities", nice: true },
    marks: [
      Plot.barY(buckets, { x: "label", y: "count", fill: "#2a5bd7" }),
      Plot.text(buckets, {
        x: "label",
        y: "count",
        text: (d: IncomeBucket) => String(d.count),
        dy: -6,
        fontSize: 11,
        fill: "#333",
      }),
    ],
  });
  return (node as unknown as { outerHTML: string }).outerHTML;
}

export function renderRegistrationTrend(
  cohort: RegistrationCohort[],
  opts: { width?: number; height?: number } = {},
): string {
  if (cohort.length === 0) return "";
  const width = opts.width ?? 480;
  const height = opts.height ?? 180;
  const node = Plot.plot({
    width,
    height,
    marginTop: 16,
    marginRight: 12,
    marginBottom: 32,
    marginLeft: 40,
    x: { label: null, tickFormat: (d: unknown) => String(d) },
    y: { grid: true, label: "Net new charities", nice: true },
    marks: [
      Plot.ruleY([0]),
      Plot.lineY(cohort, { x: "year", y: "net", stroke: "#2a5bd7", strokeWidth: 1.5 }),
      Plot.dot(cohort, { x: "year", y: "net", r: 2.5, fill: "#2a5bd7" }),
    ],
  });
  return (node as unknown as { outerHTML: string }).outerHTML;
}
```

- [ ] **Step 2: Verify TypeScript**

Run:
```
cd ui && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add ui/src/lib/chart.ts
git commit -m "feat(ui): chart helpers for income buckets + registration trend"
```

### Task 14: Chart wrapper components

**Files:**
- Create: `ui/src/components/IncomeBucketsChart.astro`
- Create: `ui/src/components/RegistrationTrendChart.astro`

- [ ] **Step 1: Write the income buckets wrapper**

`ui/src/components/IncomeBucketsChart.astro`:

```astro
---
import "../lib/dom-polyfill";
import { renderIncomeBuckets } from "../lib/chart";
import type { IncomeBucket } from "../lib/types";

interface Props {
  buckets: IncomeBucket[];
  caption?: string;
}

const { buckets, caption } = Astro.props;
const svg = renderIncomeBuckets(buckets);
---

{svg && (
  <figure class="chart-figure">
    <div class="chart" set:html={svg} aria-hidden="true" />
    {caption && <figcaption>{caption}</figcaption>}
  </figure>
)}

<style>
  .chart-figure { margin: 0; color: #2a5bd7; }
  .chart-figure .chart svg { width: 100%; height: auto; }
  .chart-figure figcaption {
    font-size: 0.75rem;
    color: #666;
    margin-top: 0.25rem;
  }
</style>
```

- [ ] **Step 2: Write the registration trend wrapper**

`ui/src/components/RegistrationTrendChart.astro`:

```astro
---
import "../lib/dom-polyfill";
import { renderRegistrationTrend } from "../lib/chart";
import type { RegistrationCohort } from "../lib/types";

interface Props {
  cohort: RegistrationCohort[];
  caption?: string;
}

const { cohort, caption } = Astro.props;
const svg = renderRegistrationTrend(cohort);
---

{svg && (
  <figure class="chart-figure">
    <div class="chart" set:html={svg} aria-hidden="true" />
    {caption && <figcaption>{caption}</figcaption>}
  </figure>
)}

<style>
  .chart-figure { margin: 0; color: #2a5bd7; }
  .chart-figure .chart svg { width: 100%; height: auto; }
  .chart-figure figcaption {
    font-size: 0.75rem;
    color: #666;
    margin-top: 0.25rem;
  }
</style>
```

- [ ] **Step 3: Verify TypeScript**

Run:
```
cd ui && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add ui/src/components/IncomeBucketsChart.astro ui/src/components/RegistrationTrendChart.astro
git commit -m "feat(ui): IncomeBucketsChart + RegistrationTrendChart components"
```

### Task 15: CivilSocietyPanel component

**Files:**
- Create: `ui/src/components/CivilSocietyPanel.astro`

- [ ] **Step 1: Write the panel**

```astro
---
import IncomeBucketsChart from "./IncomeBucketsChart.astro";
import RegistrationTrendChart from "./RegistrationTrendChart.astro";
import SourceCitations from "./SourceCitations.astro";
import { getCivilSocietyProfile } from "../lib/api";
import type { CivilSocietyProfile } from "../lib/types";

interface Props {
  placeId: string;
  cookieHeader?: string;
}

const { placeId, cookieHeader } = Astro.props;

// CC bulk register covers England + Wales registered charities only.
// Skip the panel entirely for Scotland / NI place ids so we don't show
// an honest-but-misleading "0 charities" for County Durham equivalents.
const isEnglandOrWales =
  placeId.startsWith("ltla24:E") || placeId.startsWith("ltla24:W") ||
  placeId.startsWith("utla24:E") || placeId.startsWith("utla24:W");

let profile: CivilSocietyProfile | null = null;
let error: string | null = null;

if (isEnglandOrWales) {
  try {
    profile = await getCivilSocietyProfile(placeId, { cookieHeader });
  } catch (err) {
    error = err instanceof Error ? err.message : String(err);
  }
}

function fmtGBP(value: number | null): string {
  if (value === null) return "—";
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
    maximumFractionDigits: 0,
  }).format(value);
}

function fmtInt(value: number): string {
  return new Intl.NumberFormat("en-GB").format(value);
}
---

{error && (
  <p class="error">Couldn't load civil society profile: {error}</p>
)}

{profile && profile.total_organisations > 0 && (
  <section class="cs-panel">
    <h3>Civil society</h3>

    <div class="cs-headlines">
      <div class="cs-stat">
        <span class="stat-value">{fmtInt(profile.total_organisations)}</span>
        <span class="stat-label">registered charities</span>
      </div>
      <div class="cs-stat">
        <span class="stat-value">{fmtGBP(profile.median_income)}</span>
        <span class="stat-label">median annual income</span>
      </div>
      <div class="cs-stat">
        <span class="stat-value">{fmtGBP(profile.mean_income)}</span>
        <span class="stat-label">mean annual income</span>
      </div>
    </div>

    <div class="cs-charts">
      <div>
        <h4>Income distribution</h4>
        <IncomeBucketsChart buckets={profile.income_buckets} />
      </div>
      <div>
        <h4>Net new charities per year</h4>
        <RegistrationTrendChart cohort={profile.registration_cohort} />
      </div>
    </div>

    {profile.caveats.length > 0 && (
      <ul class="caveats">
        {profile.caveats.map((c) => <li>{c}</li>)}
      </ul>
    )}

    {profile.sources.length > 0 && <SourceCitations sources={profile.sources} />}
  </section>
)}

<style>
  .cs-panel {
    margin-top: 2rem;
    padding-top: 1.5rem;
    border-top: 1px solid #e0e0e0;
  }
  .cs-panel h3 {
    margin: 0 0 1rem;
    font-size: 1.25rem;
  }
  .cs-panel h4 {
    margin: 0 0 0.5rem;
    font-size: 0.9375rem;
    color: #555;
  }
  .cs-headlines {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
  }
  .cs-stat {
    display: flex;
    flex-direction: column;
    padding: 0.75rem 1rem;
    background: #f6f7fb;
    border-radius: 6px;
  }
  .stat-value {
    font-size: 1.5rem;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }
  .stat-label {
    font-size: 0.8125rem;
    color: #555;
    margin-top: 0.125rem;
  }
  .cs-charts {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 1.5rem;
  }
  .caveats {
    margin: 1rem 0 0;
    padding-left: 1rem;
    font-size: 0.8125rem;
    color: #555;
  }
  .error { color: #a00; }
</style>
```

- [ ] **Step 2: Verify TypeScript**

Run:
```
cd ui && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add ui/src/components/CivilSocietyPanel.astro
git commit -m "feat(ui): CivilSocietyPanel — total, headlines, income + trend charts"
```

### Task 16: Mount CivilSocietyPanel on `/place/[id]`, remove OrganisationsSection

**Files:**
- Modify: `ui/src/pages/place/[id].astro:1-115`
- Delete: `ui/src/components/OrganisationsSection.astro`

- [ ] **Step 1: Swap the import**

In `ui/src/pages/place/[id].astro`, replace the `OrganisationsSection` import with `CivilSocietyPanel`:

```typescript
import CivilSocietyPanel from "../../components/CivilSocietyPanel.astro";
```

(Remove the line `import OrganisationsSection from "../../components/OrganisationsSection.astro";`.)

- [ ] **Step 2: Swap the mount**

Find:

```astro
      <OrganisationsSection placeId={profile.place.id} cookieHeader={cookieHeader} />
```

Replace with:

```astro
      <CivilSocietyPanel placeId={profile.place.id} cookieHeader={cookieHeader} />
```

- [ ] **Step 3: Delete the old component**

```bash
rm ui/src/components/OrganisationsSection.astro
```

- [ ] **Step 4: Verify TypeScript**

Run:
```
cd ui && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/place/'[id]'.astro ui/src/components/CivilSocietyPanel.astro
git rm ui/src/components/OrganisationsSection.astro
git commit -m "feat(ui): mount CivilSocietyPanel on /place/[id]; remove OrganisationsSection"
```

---

# Block 6: re-run the CC loader against the dev DB + smoke

### Task 17: Re-load CC bulk register so `raw` carries the new fields

This is an operational step. The dev DB has 1,034 orgs but their `raw` JSONB is missing `latest_income`, `date_of_registration`, `date_of_removal`. The new loader code will populate them on next run.

- [ ] **Step 1: Rebuild + restart the server image so it ships the new client**

The loader runs in the `soundings-server` image. Rebuild it without cache (other recent infra fixes have shown the build can stick to stale layers).

```
cd /Users/tomcwxyz/code/dataforaction-tom/soundings && \
  docker compose -f infra/docker-compose.yml --project-directory . build --no-cache server && \
  docker compose -f infra/docker-compose.yml --project-directory . up -d server loader pre_warmer
```

Expected: containers come up cleanly, `docker ps` shows them all healthy / running.

- [ ] **Step 2: Run the CC loader against the dev DB**

The simplest path is the CLI module the loader daemon already wraps:

```
docker compose -f infra/docker-compose.yml --project-directory . exec server \
  python -m soundings.loader.run --once charity_commission
```

Expected: a few minutes of output, ending with the upsert count (≈220k charities filtered to the dev geography). If the existing CLI doesn't accept `--once <source_id>`, run the loader programmatically:

```
docker compose -f infra/docker-compose.yml --project-directory . exec server \
  python -c "import asyncio; from soundings.db.engine import get_engine; from soundings.adapters.charity_commission.loader import CharityCommissionLoader; asyncio.run(CharityCommissionLoader(get_engine()).load())"
```

- [ ] **Step 3: Sanity-check the dev DB**

```
docker exec soundings-postgres-1 psql -U soundings -d soundings -tAc \
  "SELECT COUNT(*) FILTER (WHERE raw ? 'latest_income') AS with_income, COUNT(*) AS total FROM data.organisation"
```

Expected: `with_income > 0` (in fact, near the total). If both are zero or the ratio is suspicious, the loader change didn't land — check the rebuild step.

```
docker exec soundings-postgres-1 psql -U soundings -d soundings -tAc \
  "SELECT raw->>'latest_income', raw->>'date_of_registration' FROM data.organisation LIMIT 3"
```

Expected: real values, not empty pipes.

- [ ] **Step 4: Probe the new tool against County Durham**

```
curl -s -X POST http://localhost:8001/v1/tools/get_civil_society_profile \
  -H 'content-type: application/json' \
  -d '{"place_id":"ltla24:E06000047"}' | python3 -m json.tool | head -40
```

Expected: a JSON document with `total_organisations` around 1,000, populated `income_buckets`, a multi-year `registration_cohort`, and reasonable `median_income`/`mean_income`.

### Task 18: Browser smoke

- [ ] **Step 1: Open the place page**

Visit http://localhost:4321/place/ltla24:E06000047 in a browser.

Expected: the `Civil society` section renders with three headline stats, two charts (income buckets bar, registration trend line), and source citation. No "fetch failed" banner. No `OrganisationsSection` panel underneath.

- [ ] **Step 2: Smoke a place in Wales**

Visit http://localhost:4321/place/ltla24:W06000023 (Powys) or any Welsh LTLA.

Expected: panel renders with non-zero totals (Wales is covered by the CC bulk register).

- [ ] **Step 3: Smoke a place in Scotland**

Visit http://localhost:4321/place/ltla24:S12000033 (Aberdeen City).

Expected: panel does NOT render (England+Wales gate). Page otherwise loads normally.

- [ ] **Step 4: Commit a runbook entry**

Create `docs/runbook-civil-society-smoke.md`:

```markdown
# Runbook — civil society panel smoke

After any change to `data.organisation`, the CC loader, the
`get_civil_society_profile` orchestrator method, or the
`<CivilSocietyPanel>` component:

1. Ensure `make up` and the CC loader has been re-run since the change.
2. Visit `/place/ltla24:E06000047` (County Durham) — expect ~1,000
   charities, populated income chart and registration trend.
3. Visit `/place/ltla24:W06000023` (Powys) — expect non-zero totals.
4. Visit `/place/ltla24:S12000033` (Aberdeen) — expect the panel to be
   suppressed; rest of the page should still render.

If the panel renders but `median_income` is `null` or all bucket
counts are 0, re-run the CC loader: the `raw` JSONB on
`data.organisation` is probably missing the income/date fields the
panel depends on.
```

Commit:

```bash
git add docs/runbook-civil-society-smoke.md
git commit -m "docs(runbook): civil society panel smoke"
```

### Task 19: Final regression run

- [ ] **Step 1: Full non-live suite**

```
cd server && DATABASE_URL="postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings_test" uv run pytest -m "not live"
```

Expected: all green. Count should be the previous total plus the new tests added by this plan.

- [ ] **Step 2: Lint + type**

```
cd /Users/tomcwxyz/code/dataforaction-tom/soundings && make lint type
```

Expected: clean.

- [ ] **Step 3: Update PLAN.md and STATE.md**

Append to `PLAN.md` under "Tasks":

```markdown
- [x] Phase 6 — Civil society profile slice (`get_civil_society_profile` tool + panel). Follow-ups: funder rollup, map, ask interface.
```

Update the State table in `STATE.md` to add:

```markdown
| **`get_civil_society_profile` tool + CivilSocietyPanel** | ✅ Phase 6 slice 1 | Total, income distribution + median/mean, registration cohort trend. CC loader extended to capture `latest_income`, `date_of_registration`, `date_of_removal`. |
```

Commit:

```bash
git add PLAN.md STATE.md
git commit -m "docs: civil society profile slice 1 shipped"
```

---

## Done

Branch is ready for PR review. Open a PR against `main` from the working branch summarising:

- New tool `get_civil_society_profile` returning total + income distribution + median/mean + registration cohort.
- CC loader captures `latest_income`, `date_of_registration`, `date_of_removal`.
- `<CivilSocietyPanel>` replaces `<OrganisationsSection>` on `/place/[id]`.
- ≈8 new tests across contracts, orchestrator, HTTP, tool spec.
- Funder rollup, map, ask interface explicitly deferred to subsequent slices.

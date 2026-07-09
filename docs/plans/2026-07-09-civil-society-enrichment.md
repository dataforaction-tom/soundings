# Civil Society Enrichment Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Make the civil society profile genuinely insightful — surface notable charities (oldest, largest, newest), chart cause-area distribution, plot charity locations on a map, and enrich org cards with registration dates — instead of just listing income-sorted charity cards.

**Architecture:** Three layers of change: (1) query data already in the DB's `raw` JSONB but never surfaced (registration dates per-org, classification aggregation, notable-org queries), (2) capture lat/lon from NSPL + postcodes.io into `geography.postcode` so charity postcodes can be mapped, (3) extend the block schema + map renderer + system prompt to teach the LLM to use the new visualisations.

**Tech Stack:** FastAPI (server), Astro 5 (UI), SQLAlchemy + raw SQL, PostGIS, MapLibre GL (maps), Pydantic v2 (contracts), Vitest (UI tests), pytest (server tests)

---

## Current State

**What the DB holds but we never query:**
- `data.organisation.raw->>'date_of_registration'` — per-org (only used for year-cohort aggregate)
- `data.organisation.raw->>'postcode'` — stored, never surfaced in `OrganisationRef`
- `data.organisation.classification` — free-text `charity_activities`, used only as ILIKE keyword filter, never aggregated into a cause-area distribution
- `data.organisation_operates_in` — the join runs in `_find_via_cc_loader` but `operates_in_place_ids` is hardcoded to `[]`

**What's available from NSPL/postcodes.io but never stored:**
- NSPL CSV has `lat` and `long` columns (decimal degrees) — we map 7 area-code columns but skip coordinates
- postcodes.io API returns `latitude` and `longitude` in every result — `PostcodeLookup._map_to_lookup()` doesn't capture them
- `geography.postcode` has no lat/lon columns

**Block schema gaps:**
- `MapOverlay.source` is `Literal["amenities"]` only — no way to plot org locations
- No "nugget" block type, but `insight-callout` already works for this (severity + headline + evidence)

**System prompt gaps:**
- No guidance for notable orgs (oldest/largest/newest)
- No guidance for cause-area composition chart
- No guidance for org map overlay
- Org cards: no registration date, no "also operates in"

---

## Task List

### Task 1: Add `NotableOrgs` to `CivilSocietyProfile` contract

**Objective:** Add a `NotableOrgs` model with oldest/newest/largest charity fields to the profile contract.

**Files:**
- Modify: `server/soundings/contracts/civil_society.py`

**Step 1: Write the model**

Add to `server/soundings/contracts/civil_society.py`:

```python
class NotableOrg(BaseModel):
    id: str = Field(description="Organisation ID, e.g. 'charity_commission:123456'.")
    name: str
    register_url: str | None = None
    latest_income: float | None = None
    date_of_registration: str | None = Field(
        default=None,
        description="ISO date string from CC raw data, if available.",
    )
    year_registered: int | None = None


class NotableOrgs(BaseModel):
    oldest: NotableOrg | None = None
    newest: NotableOrg | None = None
    largest: NotableOrg | None = None
    income_concentration_top3_pct: float | None = Field(
        default=None,
        description="Top-3 charities' share of total reported income (0-100). None when <3 charities report income.",
    )
    income_concentration_top3_total: float | None = Field(
        default=None,
        description="Combined income of the top 3 charities, GBP.",
    )
```

Add to `CivilSocietyProfile`:

```python
    notable: NotableOrgs = Field(
        default_factory=NotableOrgs,
        description="Standout charities: oldest, newest, largest, and income concentration.",
    )
```

**Step 2: Verify import works**

Run: `docker exec soundings-server-1 python -c "from soundings.contracts.civil_society import NotableOrgs, NotableOrg; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add server/soundings/contracts/civil_society.py
git commit -m "feat(civil-society): add NotableOrgs to CivilSocietyProfile contract"
```

---

### Task 2: Add `date_of_registration` and `postcode` to `OrganisationRef`

**Objective:** Surface registration date and postcode from the CC raw JSONB on each org ref.

**Files:**
- Modify: `server/soundings/contracts/organisation.py`

**Step 1: Add fields**

Add to `OrganisationRef` in `server/soundings/contracts/organisation.py`:

```python
    date_of_registration: str | None = Field(
        default=None,
        description="ISO date string from the CC raw record, if available.",
    )
    postcode: str | None = Field(
        default=None,
        description="Registered address postcode (raw CC format, may include spaces).",
    )
```

**Step 2: Verify import**

Run: `docker exec soundings-server-1 python -c "from soundings.contracts.organisation import OrganisationRef; o = OrganisationRef(id='x', name='y', source=None); print(o.date_of_registration, o.postcode)"`
Expected: `None None`

Wait — `SourceRef` is required. Fix the test:

Run: `docker exec soundings-server-1 python -c "
from soundings.contracts.organisation import OrganisationRef
from soundings.contracts.source_ref import SourceRef
from datetime import datetime, timezone
s = SourceRef(source_id='x', source_label='x', publisher='', licence='', retrieved_at=datetime.now(timezone.utc), cache_status='cached')
o = OrganisationRef(id='x', name='y', source=s)
print(o.date_of_registration, o.postcode)
"`
Expected: `None None`

**Step 3: Commit**

```bash
git add server/soundings/contracts/organisation.py
git commit -m "feat(civil-society): add date_of_registration + postcode to OrganisationRef"
```

---

### Task 3: Add `CauseAreaCount` to `CivilSocietyProfile` contract

**Objective:** Add a cause-area distribution model so the profile can carry a composition-chart-ready breakdown.

**Files:**
- Modify: `server/soundings/contracts/civil_society.py`

**Step 1: Write the model**

Add to `server/soundings/contracts/civil_society.py`:

```python
class CauseAreaCount(BaseModel):
    label: str = Field(description="Cause-area label (free-text classification from CC charity_activities).")
    count: int = Field(ge=0, description="Number of charities in this cause area.")
```

Add to `CivilSocietyProfile`:

```python
    cause_area_distribution: list[CauseAreaCount] = Field(
        default_factory=list,
        description=(
            "Top cause areas by charity count, derived from CC free-text"
            " charity_activities. Labels are raw free-text, not structured"
            " classification codes — treat as approximate. Empty when no"
            " charities have activities text."
        ),
    )
```

**Step 2: Verify import**

Run: `docker exec soundings-server-1 python -c "from soundings.contracts.civil_society import CauseAreaCount; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add server/soundings/contracts/civil_society.py
git commit -m "feat(civil-society): add cause_area_distribution to profile contract"
```

---

### Task 4: Query notable orgs in `compute_civil_society_profile`

**Objective:** Add SQL queries for oldest/newest/largest charity and income concentration, populate `NotableOrgs`.

**Files:**
- Modify: `server/soundings/orchestration/orchestrator.py` (in `compute_civil_society_profile`, before the `return CivilSocietyProfile(...)` at line ~1183)

**Step 1: Add the query**

Inside the `async with self._engine.connect() as conn:` block (after the cohort query, before the block ends), add:

```python
            # Notable orgs: oldest, newest, largest by income.
            notable_row = (
                await conn.execute(
                    text(
                        """
                        WITH orgs AS (
                            SELECT o.id, o.name,
                                   (o.raw->>'latest_income')::numeric AS income,
                                   (o.raw->>'date_of_registration')::date AS reg_date,
                                   o.raw->>'postcode' AS postcode
                            FROM data.organisation_operates_in oi
                            JOIN data.organisation o ON o.id = oi.organisation_id
                            WHERE oi.place_id = :pid
                        """
                        f"{kw_sql}"
                        """
                        )
                        SELECT
                            (SELECT id FROM orgs WHERE reg_date IS NOT NULL
                             ORDER BY reg_date ASC LIMIT 1) AS oldest_id,
                            (SELECT name FROM orgs WHERE reg_date IS NOT NULL
                             ORDER BY reg_date ASC LIMIT 1) AS oldest_name,
                            (SELECT reg_date FROM orgs WHERE reg_date IS NOT NULL
                             ORDER BY reg_date ASC LIMIT 1) AS oldest_date,
                            (SELECT income FROM orgs WHERE reg_date IS NOT NULL
                             ORDER BY reg_date ASC LIMIT 1) AS oldest_income,
                            (SELECT postcode FROM orgs WHERE reg_date IS NOT NULL
                             ORDER BY reg_date ASC LIMIT 1) AS oldest_postcode,
                            (SELECT id FROM orgs WHERE reg_date IS NOT NULL
                             ORDER BY reg_date DESC LIMIT 1) AS newest_id,
                            (SELECT name FROM orgs WHERE reg_date IS NOT NULL
                             ORDER BY reg_date DESC LIMIT 1) AS newest_name,
                            (SELECT reg_date FROM orgs WHERE reg_date IS NOT NULL
                             ORDER BY reg_date DESC LIMIT 1) AS newest_date,
                            (SELECT income FROM orgs WHERE reg_date IS NOT NULL
                             ORDER BY reg_date DESC LIMIT 1) AS newest_income,
                            (SELECT postcode FROM orgs WHERE reg_date IS NOT NULL
                             ORDER BY reg_date DESC LIMIT 1) AS newest_postcode,
                            (SELECT id FROM orgs WHERE income IS NOT NULL
                             ORDER BY income DESC LIMIT 1) AS largest_id,
                            (SELECT name FROM orgs WHERE income IS NOT NULL
                             ORDER BY income DESC LIMIT 1) AS largest_name,
                            (SELECT income FROM orgs WHERE income IS NOT NULL
                             ORDER BY income DESC LIMIT 1) AS largest_income,
                            (SELECT reg_date FROM orgs WHERE income IS NOT NULL
                             ORDER BY income DESC LIMIT 1) AS largest_date,
                            (SELECT postcode FROM orgs WHERE income IS NOT NULL
                             ORDER BY income DESC LIMIT 1) AS largest_postcode,
                            (SELECT SUM(income) FROM orgs WHERE income IS NOT NULL) AS total_income,
                            (SELECT SUM(income) FROM (
                                SELECT income FROM orgs WHERE income IS NOT NULL
                                ORDER BY income DESC LIMIT 3
                            ) t) AS top3_income,
                            (SELECT COUNT(*) FROM orgs WHERE income IS NOT NULL) AS income_count
                        """
                    ),
                    {"pid": place_id, **kw_params},
                )
            ).first()
```

Then after the `async with` block (where caveats are built), add:

```python
        notable = NotableOrgs()
        if notable_row:
            def _build_notable(nid: str | None, name: str | None, income, reg_date, postcode) -> NotableOrg | None:
                if not nid:
                    return None
                reg_no = nid.split(":", 1)[1] if ":" in nid else None
                url = (
                    f"https://register-of-charities.charitycommission.gov.uk/charity-search-/charity-details/{reg_no}"
                    if reg_no else None
                )
                year = None
                if reg_date is not None:
                    try:
                        year = int(str(reg_date)[:4])
                    except (ValueError, TypeError):
                        pass
                return NotableOrg(
                    id=nid,
                    name=name or "",
                    register_url=url,
                    latest_income=float(income) if income is not None else None,
                    date_of_registration=str(reg_date) if reg_date is not None else None,
                    year_registered=year,
                )

            notable = NotableOrgs(
                oldest=_build_notable(
                    notable_row.oldest_id, notable_row.oldest_name,
                    notable_row.oldest_income, notable_row.oldest_date, notable_row.oldest_postcode,
                ),
                newest=_build_notable(
                    notable_row.newest_id, notable_row.newest_name,
                    notable_row.newest_income, notable_row.newest_date, notable_row.newest_postcode,
                ),
                largest=_build_notable(
                    notable_row.largest_id, notable_row.largest_name,
                    notable_row.largest_income, notable_row.largest_date, notable_row.largest_postcode,
                ),
                income_concentration_top3_total=(
                    float(notable_row.top3_income)
                    if notable_row.top3_income is not None else None
                ),
                income_concentration_top3_pct=(
                    round(float(notable_row.top3_income) / float(notable_row.total_income) * 100, 1)
                    if notable_row.top3_income is not None
                    and notable_row.total_income is not None
                    and notable_row.total_income > 0
                    and int(notable_row.income_count) >= 3
                    else None
                ),
            )
```

Add `notable=notable` to the `CivilSocietyProfile(...)` constructor call.

Add `from soundings.contracts.civil_society import NotableOrg, NotableOrgs` to the imports at the top of the method (or file-level if not already).

**Step 2: Verify**

Run: `docker exec soundings-server-1 python -c "from soundings.orchestration.orchestrator import IndicatorOrchestrator; print('ok')"`

**Step 3: Commit**

```bash
git add server/soundings/orchestration/orchestrator.py
git commit -m "feat(civil-society): query notable orgs (oldest/newest/largest) in profile"
```

---

### Task 5: Query cause-area distribution in `compute_civil_society_profile`

**Objective:** Aggregate `classification` (free-text `charity_activities`) into a top-N cause-area distribution.

**Files:**
- Modify: `server/soundings/orchestration/orchestrator.py` (in `compute_civil_society_profile`, inside the `async with` block)

**Step 1: Add the query**

Inside the `async with self._engine.connect() as conn:` block, after the notable query, add:

```python
            # Cause-area distribution: aggregate the free-text classification
            # (charity_activities) into a top-10 breakdown. Each org has 0 or 1
            # classification entries (the full activities text as one string).
            # We group by the full text and count. This is noisy but useful for
            # a rough composition chart.
            cause_rows = (
                await conn.execute(
                    text(
                        """
                        SELECT unnest(o.classification) AS cause, COUNT(*) AS n
                        FROM data.organisation_operates_in oi
                        JOIN data.organisation o ON o.id = oi.organisation_id
                        WHERE oi.place_id = :pid
                          AND o.classification != '{}'
                        """
                        f"{kw_sql}"
                        """
                        GROUP BY cause
                        ORDER BY n DESC
                        LIMIT 10
                        """
                    ),
                    {"pid": place_id, **kw_params},
                )
            ).all()
            cause_area_distribution = [
                CauseAreaCount(label=r.cause[:120], count=int(r.n))
                for r in cause_rows
                if r.cause and r.cause.strip()
            ]
```

Add `from soundings.contracts.civil_society import CauseAreaCount` to imports.

Add `cause_area_distribution=cause_area_distribution` to the `CivilSocietyProfile(...)` constructor.

**Step 2: Verify**

Run: `docker exec soundings-server-1 python -c "from soundings.orchestration.orchestrator import IndicatorOrchestrator; print('ok')"`

**Step 3: Commit**

```bash
git add server/soundings/orchestration/orchestrator.py
git commit -m "feat(civil-society): aggregate cause-area distribution in profile"
```

---

### Task 6: Surface `date_of_registration`, `postcode`, and `operates_in_place_ids` in `_find_via_cc_loader`

**Objective:** Extend the SELECT to pull `date_of_registration` and `postcode` from `raw`, and collect `operates_in_place_ids` from the existing join instead of hardcoding `[]`.

**Files:**
- Modify: `server/soundings/orchestration/orchestrator.py` (`_find_via_cc_loader` method, lines ~724-815)

**Step 1: Extend the SQL query**

Change the SELECT in `_find_via_cc_loader` to also extract `date_of_registration` and `postcode` from `raw`, and collect the operates_in place_ids:

```python
            rows = await conn.execute(
                text(
                    """
                    SELECT o.id, o.name, o.classification,
                           o.registered_address_place_id, o.source_id, o.retrieved_at,
                           (o.raw->>'latest_income')::numeric AS latest_income,
                           o.raw->>'date_of_registration' AS date_of_registration,
                           o.raw->>'postcode' AS postcode,
                           array_agg(DISTINCT oi.place_id) FILTER (WHERE oi.place_id IS NOT NULL) AS operates_in
                    FROM data.organisation o
                    LEFT JOIN data.organisation_operates_in oi
                        ON oi.organisation_id = o.id
                    WHERE (o.registered_address_place_id = :pid
                        OR oi.place_id = :pid)
                    """  # noqa: S608
                    f"{kw_sql}"
                    " GROUP BY o.id, o.name, o.classification,"
                    "          o.registered_address_place_id, o.source_id, o.retrieved_at,"
                    "          o.raw"
                    " ORDER BY MAX((o.raw->>'latest_income')::numeric) DESC NULLS LAST"
                    " LIMIT :limit"
                ),
                {"pid": place_id, "limit": limit, **kw_params},
            )
```

**Step 2: Update the org-building loop**

In the loop where `OrganisationRef` is constructed (line ~776), change:

```python
            orgs.append(
                OrganisationRef(
                    id=row.id,
                    name=row.name,
                    classification=list(row.classification or []),
                    registered_address_place_id=row.registered_address_place_id,
                    operates_in_place_ids=list(row.operates_in or []),
                    recent_grants=[],
                    latest_income=income,
                    register_url=register_url,
                    date_of_registration=row.date_of_registration,
                    postcode=row.postcode,
                    source=SourceRef(
                        source_id=source_id,
                        source_label=source_id,
                        publisher="",
                        licence="",
                        retrieved_at=row.retrieved_at or now,
                        cache_status="cached",
                    ),
                )
            )
```

**Step 3: Verify**

Run: `docker exec soundings-server-1 python -c "from soundings.orchestration.orchestrator import IndicatorOrchestrator; print('ok')"`

**Step 4: Commit**

```bash
git add server/soundings/orchestration/orchestrator.py
git commit -m "feat(civil-society): surface registration date, postcode, operates_in on org refs"
```

---

### Task 7: Add lat/lon columns to `geography.postcode` (migration)

**Objective:** Add `latitude` and `longitude` numeric columns to `geography.postcode` so charity postcodes can be mapped.

**Files:**
- Create: `server/soundings/db/migrations/versions/0007_postcode_latlon.py`

**Step 1: Write the migration**

```python
"""add lat/lon to geography.postcode

Revision ID: 0007_postcode_latlon
Revises: 0006_answer_cache
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_postcode_latlon"
down_revision = "0006_answer_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "postcode",
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        schema="geography",
    )
    op.add_column(
        "postcode",
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        schema="geography",
    )


def downgrade() -> None:
    op.drop_column("postcode", "longitude", schema="geography")
    op.drop_column("postcode", "latitude", schema="geography")
```

**Step 2: Check current head**

Run: `docker exec soundings-server-1 alembic heads`
Expected: should show `0006_answer_cache` as the current head.

**Step 3: Apply migration**

Run: `docker exec soundings-server-1 alembic upgrade head`
Expected: `Running upgrade 0006_answer_cache -> 0007_postcode_latlon`

**Step 4: Verify columns**

Run: `docker exec soundings-postgres-1 psql -U soundings -d soundings -c "\d geography.postcode" | grep -E 'latitude|longitude'`
Expected: two rows showing `latitude` and `longitude` columns.

**Step 5: Commit**

```bash
git add server/soundings/db/migrations/versions/0007_postcode_latlon.py
git commit -m "feat(db): add latitude/longitude columns to geography.postcode (migration 0007)"
```

---

### Task 8: Add lat/lon to `Postcode` model and `PostcodeLookup`

**Objective:** Update the SQLAlchemy model and the postcodes.io lookup DTO to carry coordinates.

**Files:**
- Modify: `server/soundings/db/models/geography.py` (Postcode class)
- Modify: `server/soundings/adapters/postcodes_io/adapter.py` (PostcodeLookup + _map_to_lookup + _upsert_postcode_stmt)

**Step 1: Add columns to Postcode model**

In `server/soundings/db/models/geography.py`, add to the `Postcode` class:

```python
from sqlalchemy import Numeric
# ... (add to imports if not already present)

    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
```

**Step 2: Add fields to PostcodeLookup**

In `server/soundings/adapters/postcodes_io/adapter.py`, add to `PostcodeLookup`:

```python
    latitude: float | None
    longitude: float | None
```

Update `with_fk_safe` to carry them through:

```python
        return PostcodeLookup(
            postcode=self.postcode,
            lsoa21=keep(self.lsoa21),
            msoa21=keep(self.msoa21),
            ltla24=keep(self.ltla24),
            utla24=keep(self.utla24),
            ward24=keep(self.ward24),
            westminster_constituency_24=keep(self.westminster_constituency_24),
            region=keep(self.region),
            country=keep(self.country),
            latitude=self.latitude,
            longitude=self.longitude,
        )
```

**Step 3: Update `_map_to_lookup`**

In `_map_to_lookup`, extract lat/lon from the postcodes.io response:

```python
    @staticmethod
    def _map_to_lookup(postcode: str | None, payload: dict[str, Any]) -> PostcodeLookup:
        result = payload.get("result", {})
        codes = result.get("codes", {}) if isinstance(result, dict) else {}
        return PostcodeLookup(
            postcode=postcode or "",
            lsoa21=_qualified("lsoa21", codes.get("lsoa")),
            msoa21=_qualified("msoa21", codes.get("msoa")),
            ltla24=_qualified("ltla24", codes.get("admin_district")),
            utla24=_qualified("utla24", codes.get("admin_county") or codes.get("admin_district")),
            ward24=_qualified("ward24", codes.get("admin_ward")),
            westminster_constituency_24=_qualified(
                "westminster_constituency_24",
                codes.get("parliamentary_constituency_2024")
                or codes.get("parliamentary_constituency"),
            ),
            region=_qualified("region", codes.get("region")),
            country=_qualified("country", codes.get("country")),
            latitude=_coerce_optional_float(result.get("latitude")),
            longitude=_coerce_optional_float(result.get("longitude")),
        )
```

Add helper:

```python
def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
```

**Step 4: Update `_upsert_postcode_stmt`**

Add `latitude` and `longitude` to the upsert SQL. Read the current function and add the two columns to both the INSERT column list, the VALUES, and the ON CONFLICT DO UPDATE SET.

**Step 5: Verify**

Run: `docker exec soundings-server-1 python -c "from soundings.adapters.postcodes_io.adapter import PostcodeLookup; print(PostcodeLookup(postcode='x', lsoa21=None, msoa21=None, ltla24=None, utla24=None, ward24=None, westminster_constituency_24=None, region=None, country=None, latitude=54.5, longitude=-1.3).latitude)"`
Expected: `54.5`

**Step 6: Commit**

```bash
git add server/soundings/db/models/geography.py server/soundings/adapters/postcodes_io/adapter.py
git commit -m "feat(geography): add lat/lon to Postcode model + PostcodeLookup"
```

---

### Task 9: Capture lat/lon in NSPL loader

**Objective:** Extend the NSPL loader to read `lat` and `long` columns from the CSV and store them in `geography.postcode`.

**Files:**
- Modify: `server/soundings/adapters/ons_nspl/loader.py`

**Step 1: Extend the column map and upsert SQL**

Add `lat` and `long` to the upsert SQL. The NSPL CSV has columns `lat` and `long` (decimal degrees). Add them to `_UPSERT_SQL`:

```python
_UPSERT_SQL = text(
    "INSERT INTO geography.postcode "
    "(postcode, lsoa21, msoa21, ltla24, ward24, "
    " westminster_constituency_24, region, country, latitude, longitude, retrieved_at) "
    "VALUES (:postcode, :lsoa21, :msoa21, :ltla24, :ward24, "
    "        :westminster_constituency_24, :region, :country, :latitude, :longitude, :retrieved_at) "
    "ON CONFLICT (postcode) DO UPDATE SET "
    "  lsoa21 = EXCLUDED.lsoa21, msoa21 = EXCLUDED.msoa21, "
    "  ltla24 = EXCLUDED.ltla24, ward24 = EXCLUDED.ward24, "
    "  westminster_constituency_24 = EXCLUDED.westminster_constituency_24, "
    "  region = EXCLUDED.region, country = EXCLUDED.country, "
    "  latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude, "
    "  retrieved_at = EXCLUDED.retrieved_at"
)
```

In the row-building section of `load()`, add lat/lon extraction from the NSPL row:

```python
            batch.append({
                "postcode": _normalise_postcode(row["pcds"]),
                "lsoa21": _qualified("lsoa21", row.get("lsoa21cd")),
                "msoa21": _qualified("msoa21", row.get("msoa21cd")),
                "ltla24": _qualified("ltla24", row.get("lad25cd")),
                "ward24": _qualified("ward24", row.get("wd25cd")),
                "westminster_constituency_24": _qualified(
                    "westminster_constituency_24", row.get("pcon24cd")
                ),
                "region": _qualified("region", row.get("rgn25cd")),
                "country": _qualified("country", row.get("ctry25cd")),
                "latitude": _coerce_float(row.get("lat")),
                "longitude": _coerce_float(row.get("long")),
                "retrieved_at": now,
            })
```

Add a `_coerce_float` helper (or import from a shared util):

```python
def _coerce_float(raw: str | None) -> float | None:
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        return None
```

**Step 2: Verify import**

Run: `docker exec soundings-server-1 python -c "from soundings.adapters.ons_nspl.loader import NsplLoader; print('ok')"`

**Step 3: Commit**

```bash
git add server/soundings/adapters/ons_nspl/loader.py
git commit -m "feat(nspl): capture lat/lon from NSPL CSV into geography.postcode"
```

---

### Task 10: Backfill lat/lon for existing postcodes

**Objective:** Populate `latitude` and `longitude` for existing `geography.postcode` rows that don't have them yet (all current rows will have NULL since the columns were just added).

**Files:**
- No new files — this is a one-shot data operation

**Step 1: Check how many postcodes need lat/lon**

Run:
```bash
docker exec soundings-postgres-1 psql -U soundings -d soundings -c \
  "SELECT COUNT(*) FILTER (WHERE latitude IS NULL) AS missing, COUNT(*) AS total FROM geography.postcode;"
```

**Step 2: Backfill from NSPL**

The simplest approach is to re-run the NSPL loader, which will upsert all rows including lat/lon:

```bash
docker exec soundings-loader-1 python -c "
import asyncio
from soundings.adapters.ons_nspl.loader import NsplLoader
from soundings.adapters.ons_nspl.client import NsplBulkClient
from soundings.core.config import get_settings
from soundings.db.engine import get_engine

async def run():
    engine = get_engine()
    settings = get_settings()
    url = settings.ons_nspl_url
    client = NsplBulkClient(url=url)
    loader = NsplLoader(engine, client)
    result = await loader.load()
    print(result)

asyncio.run(run())
"
```

This may take a few minutes. If the NSPL URL isn't configured, check `server/soundings/core/config.py` for the setting name.

Alternative (faster, if NSPL re-load is too slow): bulk-geocode via postcodes.io. But NSPL re-load is the clean path since it already has lat/lon.

**Step 3: Verify**

Run:
```bash
docker exec soundings-postgres-1 psql -U soundings -d soundings -c \
  "SELECT COUNT(*) FILTER (WHERE latitude IS NULL) AS missing, COUNT(*) AS total FROM geography.postcode;"
```

Expected: `missing` should be significantly reduced (some will remain for postcodes that NSPL doesn't have coordinates for — terminated postcodes etc).

**Step 4: No commit needed** (data operation, not code)

---

### Task 11: Add `/v1/place/{place_id}/organisations/geometry` endpoint

**Objective:** New GeoJSON endpoint returning charity locations as point features for map rendering.

**Files:**
- Modify: `server/soundings/http/place_geometry.py` (add new route)
- Modify: `server/soundings/app.py` (no new router needed — already mounted)

**Step 1: Write the endpoint**

Add to `server/soundings/http/place_geometry.py`:

```python
@router.get("/place/{place_id}/organisations/geometry")
async def get_organisations_geometry(
    request: Request,
    place_id: str,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, object]:
    """GeoJSON FeatureCollection of charity registered-address locations
    within a place. Each feature is a Point with properties: id, name,
    income, cause, register_url.

    Only charities with a postcode that resolves to a lat/lon are included.
    Charities that operate here but are registered elsewhere are NOT
    included (no coordinates for them).
    """
    engine = request.app.state.engine
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT o.id, o.name,
                           (o.raw->>'latest_income')::numeric AS income,
                           o.raw->>'postcode' AS postcode,
                           o.classification,
                           p.latitude, p.longitude
                    FROM data.organisation o
                    JOIN geography.postcode p
                        ON p.postcode = REPLACE(o.raw->>'postcode', ' ', '')
                    WHERE o.registered_address_place_id = :pid
                      AND p.latitude IS NOT NULL
                      AND p.longitude IS NOT NULL
                    ORDER BY (o.raw->>'latest_income')::numeric DESC NULLS LAST
                    LIMIT :limit
                    """
                ),
                {"pid": place_id, "limit": limit},
            )
        ).all()

    features: list[dict[str, object]] = []
    for r in rows:
        reg_no = r.id.split(":", 1)[1] if ":" in r.id else None
        register_url = (
            f"https://register-of-charities.charitycommission.gov.uk/charity-search-/charity-details/{reg_no}"
            if reg_no else None
        )
        classification = list(r.classification or [])
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(r.longitude), float(r.latitude)],
            },
            "properties": {
                "id": r.id,
                "name": r.name,
                "income": float(r.income) if r.income is not None else None,
                "cause": classification[0] if classification else None,
                "register_url": register_url,
            },
        })
    return {"type": "FeatureCollection", "features": features}
```

**Step 2: Verify**

Rebuild + restart the server:
```bash
docker-compose -f infra/docker-compose.yml --project-directory . build server
docker-compose -f infra/docker-compose.yml --project-directory . up -d server
sleep 10
```

Test:
```bash
curl -s "http://localhost:8001/v1/place/ltla24:E06000047/organisations/geometry?limit=5" | python3 -m json.tool | head -30
```

Expected: a FeatureCollection with Point features for County Durham charities.

**Step 3: Commit**

```bash
git add server/soundings/http/place_geometry.py
git commit -m "feat(api): add /v1/place/{id}/organisations/geometry GeoJSON endpoint"
```

---

### Task 12: Extend `MapOverlay` block schema to support organisations

**Objective:** Allow the LLM to emit a map block with an organisations overlay so charity locations can be plotted.

**Files:**
- Modify: `server/soundings/ask/blocks.py` (MapOverlay)

**Step 1: Update MapOverlay**

Change `MapOverlay` to:

```python
class MapOverlay(BaseModel):
    source: Literal["amenities", "organisations"]
    indicator_keys: list[str] = Field(
        default_factory=list,
        min_length=0,
        max_length=6,
        description="Required for amenities overlay; ignored for organisations overlay.",
    )
```

Note: `indicator_keys` is now optional (default empty list) since the organisations overlay doesn't use indicator keys. The `min_length=1` constraint is removed.

**Step 2: Verify**

Run: `docker exec soundings-server-1 python -c "
from soundings.ask.blocks import MapOverlay
m = MapOverlay(source='organisations')
print(m.source, m.indicator_keys)
m2 = MapOverlay(source='amenities', indicator_keys=['infrastructure.food_banks_count'])
print(m2.source, m2.indicator_keys)
"`
Expected:
```
organisations []
amenities ['infrastructure.food_banks_count']
```

**Step 3: Commit**

```bash
git add server/soundings/ask/blocks.py
git commit -m "feat(blocks): extend MapOverlay to support organisations source"
```

---

### Task 13: Add org point layer to map renderer

**Objective:** Extend the MapLibre renderer in `ask_page.ts` to fetch and display organisation point features when `overlay.source === "organisations"`.

**Files:**
- Modify: `ui/src/scripts/ask_page.ts` (map rendering section)

**Step 1: Add org point rendering**

In the map rendering section of `ask_page.ts`, find where `overlay.source === "amenities"` is handled. Add a parallel path for `"organisations"`:

```typescript
          if (overlay && overlay.source === "organisations") {
            const orgUrl = `${apiBase}/v1/place/${placeId}/organisations/geometry?limit=200`;
            try {
              const orgFc = await fetch(orgUrl).then((r) => r.json());
              if (orgFc.features && orgFc.features.length > 0) {
                map.addSource("org-points", {
                  type: "geojson",
                  data: orgFc,
                });
                map.addLayer({
                  id: "org-points",
                  type: "circle",
                  source: "org-points",
                  paint: {
                    "circle-radius": ["interpolate", ["linear"], ["get", "income"], 0, 4, 100000, 5, 1000000, 7, 10000000, 9],
                    "circle-color": "#1a2f4e",
                    "circle-stroke-color": "#faf9f6",
                    "circle-stroke-width": 1,
                    "circle-opacity": 0.8,
                  },
                });
                // Popups
                map.on("click", "org-points", (e: any) => {
                  const f = e.features?.[0];
                  if (!f) return;
                  const props = f.properties;
                  const income = props.income
                    ? Number(props.income).toLocaleString("en-GB", {
                        style: "currency",
                        currency: "GBP",
                        maximumFractionDigits: 0,
                      })
                    : "Income not reported";
                  new maplibregl.Popup({ offset: 10 })
                    .setHTML(
                      `<strong>${props.name}</strong><br/>${income}` +
                        (props.cause ? `<br/><span class="text-muted">${props.cause}</span>` : "") +
                        (props.register_url ? `<br/><a href="${props.register_url}" target="_blank">Register page →</a>` : ""),
                    )
                    .setLngLat(f.geometry.coordinates)
                    .addTo(map);
                });
                map.on("mouseenter", "org-points", () => {
                  map.getCanvas().style.cursor = "pointer";
                });
                map.on("mouseleave", "org-points", () => {
                  map.getCanvas().style.cursor = "";
                });
                // Legend entry
                const legend = host.querySelector(".map-legend");
                if (legend) {
                  const item = document.createElement("div");
                  item.className = "legend-item";
                  item.innerHTML = '<span class="legend-swatch" style="background:#1a2f4e;border-radius:50%"></span> Charities';
                  legend.appendChild(item);
                }
              }
            } catch (e) {
              console.warn("Failed to load org points:", e);
            }
          }
```

This should be placed alongside the existing amenities overlay handling, in the `else if` for organisations.

**Step 2: Verify UI tests still pass**

Run: `cd ui && npx vitest run`
Expected: 141 passing (no new tests needed yet — the renderer is integration-tested via browser).

**Step 3: Rebuild UI**

```bash
docker-compose -f infra/docker-compose.yml --project-directory . build ui
docker-compose -f infra/docker-compose.yml --project-directory . up -d ui
```

**Step 4: Commit**

```bash
git add ui/src/scripts/ask_page.ts
git commit -m "feat(ui): add organisation point layer to map renderer"
```

---

### Task 14: Update org card renderer with registration date

**Objective:** Show "Founded 1862" on org cards when `date_of_registration` is available.

**Files:**
- Modify: `ui/src/scripts/ask_page.ts` (org card rendering, ~line 498-540)
- Modify: `ui/src/components/OrganisationCard.astro`

**Step 1: Update ask_page.ts org card**

In the `renderOrganisationsBlock` function, after the income line and before the classification line, add:

```typescript
            if (org.date_of_registration) {
              const year = org.date_of_registration.substring(0, 4);
              const foundedP = document.createElement("p");
              foundedP.className = "text-muted text-small";
              foundedP.textContent = `Founded ${year}`;
              card.appendChild(foundedP);
            }
```

Also update the `OrganisationsResponse` interface to include `date_of_registration`:

```typescript
          interface OrganisationsResponse {
            organisations: {
              id: string;
              name: string;
              classification: string[];
              recent_grants: { ... }[];
              latest_income: number | null;
              register_url: string | null;
              date_of_registration: string | null;
            }[];
          }
```

**Step 2: Update OrganisationCard.astro**

Add a "Founded {year}" line to the SSR card, extracting the year from `date_of_registration` if present.

**Step 3: Verify UI tests**

Run: `cd ui && npx vitest run`
Expected: 141 passing

**Step 4: Rebuild UI**

```bash
docker-compose -f infra/docker-compose.yml --project-directory . build ui
docker-compose -f infra/docker-compose.yml --project-directory . up -d ui
```

**Step 5: Commit**

```bash
git add ui/src/scripts/ask_page.ts ui/src/components/OrganisationCard.astro
git commit -m "feat(ui): show founding year on org cards"
```

---

### Task 15: Update system prompt — civil society enrichment guidance

**Objective:** Teach the LLM to use notable orgs, cause-area charts, and org map overlay.

**Files:**
- Modify: `server/soundings/ask/prompts.py` (`_BLOCK_GUIDANCE` and civil-society enrichment section)

**Step 1: Add block guidance for organisations map overlay**

In the map block guidance section (where `overlay {source:"amenities"...}` is described), add:

```
  * org-points — set overlay {source:"organisations"} to plot charity
    registered-address locations on the map, sized by income. Use for
    "where are the charities" or "show me charity locations" questions.
    No indicator_keys needed. Pair with a text block noting how many
    charities are mapped vs total (some charities registered elsewhere
    won't appear).
```

**Step 2: Update civil-society enrichment guidance**

Replace/extend the "Civil-society enrichment guidance" section with:

```
Civil-society enrichment guidance:
- get_civil_society_profile returns TWO counts: total_organisations (charities
  that OPERATE in the place, including those registered elsewhere but
  self-declaring they operate here) and registered_address_count (charities
  with their registered address postcode in the place). total_organisations
  is always >= registered_address_count. When they differ, always present
  BOTH numbers and explain: "X charities operate in {place}, of which Y are
  registered here. The difference ({X-Y}) are charities registered elsewhere
  but operating in this area." This matches how the Charity Commission
  reports counts. Lead with total_organisations as the headline figure.
- get_civil_society_profile also returns `notable` — standout charities that
  make the answer interesting:
  * notable.oldest — the oldest registered charity still active. Lead with
    this as an insight-callout (severity: "notable") with headline like
    "Oldest charity in {place}: {name}, founded {year}". Include the
    register link in the evidence text.
  * notable.largest — the highest-income charity. Use an insight-callout or
    weave into the narrative: "The largest charity is {name} with £X/yr".
  * notable.newest — the most recently registered charity. Mention in the
    narrative if interesting (e.g. "The newest charity was registered in
    {year}").
  * notable.income_concentration_top3_pct — if >= 3 charities report income,
    this is the top-3's share of total income. When it's high (e.g. >60%),
    call it out: "The top 3 charities hold {pct}% of the sector's reported
    income — significant concentration". Use an insight-callout when
    striking.
  Use at most 1-2 insight-callouts for notable orgs — don't over-callout.
- get_civil_society_profile also returns cause_area_distribution — a top-10
  breakdown of charities by their free-text activities field. When present
  (non-empty), include a composition-chart titled "Charity causes in
  {place}" with one segment per cause area (label=cause text truncated,
  value=count). Pair with text noting the top 3 cause areas. Caveat: labels
  are free-text, not structured codes, so some may be noisy or overlapping.
- find_organisations_in_place returns charities sorted by income (largest
  first). Use an organisations block with limit 5-8 to surface the biggest
  charities. Each card includes income, founding year, and a link to the
  Charity Commission register page — mention this in your narrative.
- For "where are they" or "show me charity locations" questions, use a map
  block with overlay {source:"organisations"} to plot charity registered-
  address locations. Note that only charities with a registered address in
  the place are mapped — charities operating here but registered elsewhere
  won't appear on the map.
- get_civil_society_profile also returns top_funders — a list of funders
  ranked by total GBP awarded to charities in the place (360Giving, last 12
  months). When funders are present, include a composition-chart titled
  "Top funders in {place}" with one segment per funder (label=funder name,
  value=total_gbp). Pair it with a text block naming the top 3 funders and
  their grant counts.
- For "who funds" or "major funders" questions, lead with the funders
  composition-chart and a narrative ranking. If top_funders is empty, say
  so explicitly — 360Giving coverage varies by area.
- For "how has the sector changed" questions, use the registration_cohort
  data. Pass year_from/year_to to filter the cohort to the requested range.
  Present the filtered cohort as a bar-chart with one bar per year
  (label=year, value=net or registered) and a text summary of the trend.
- get_civil_society_profile also returns grants_by_year — a year-by-year
  breakdown of all 360Giving grants to charities in the place (full history,
  not just 12 months). For "how has funding changed" or "grants over time"
  questions, use a bar-chart with one bar per year (label=year,
  value=total_gbp) to visualise the trend. Pair with a text summary noting
  the peak year and overall direction.
- Always note that Charity Commission data covers England and Wales only;
  Scotland/NI charities have limited detail (name only, no income/grants).
```

**Step 3: Verify import**

Run: `docker exec soundings-server-1 python -c "from soundings.ask.prompts import SystemPromptBuilder; p = SystemPromptBuilder(); t = p.build(); assert 'notable' in t and 'cause_area_distribution' in t and 'organisations' in t; print('ok')"`

**Step 4: Commit**

```bash
git add server/soundings/ask/prompts.py
git commit -m "feat(prompt): teach LLM to use notable orgs, cause-area charts, org maps"
```

---

### Task 16: Wire up `top_funders` + `grants_by_year` on `CivilSocietyPanel.astro`

**Objective:** The place-page panel already receives the profile but only renders headline stats + 2 charts. Add the funder composition and grant-history bar chart.

**Files:**
- Modify: `ui/src/components/CivilSocietyPanel.astro`

**Step 1: Read the current component**

Read `ui/src/components/CivilSocietyPanel.astro` to understand the existing structure.

**Step 2: Add funder + grants sections**

After the existing charts, add:

- A "Top Funders" section: if `top_funders` is non-empty, render a simple composition list (funder name + grant count + total GBP). This is SSR — no interactive chart library needed; use a CSS-based bar or a simple table.
- A "Grants by Year" section: if `grants_by_year` is non-empty, render a simple bar chart using CSS divs (height proportional to total_gbp).

**Step 3: Verify UI tests**

Run: `cd ui && npx vitest run`
Expected: 141 passing

**Step 4: Rebuild UI**

```bash
docker-compose -f infra/docker-compose.yml --project-directory . build ui
docker-compose -f infra/docker-compose.yml --project-directory . up -d ui
```

**Step 5: Commit**

```bash
git add ui/src/components/CivilSocietyPanel.astro
git commit -m "feat(ui): render top funders + grants by year on CivilSocietyPanel"
```

---

### Task 17: Rebuild, test, and verify end-to-end

**Objective:** Full rebuild, run all tests, and verify the ask experience with a real question.

**Step 1: Rebuild all services**

```bash
cd /Users/tomcwxyz/code/dataforaction-tom/soundings
docker-compose -f infra/docker-compose.yml --project-directory . build server ui
docker-compose -f infra/docker-compose.yml --project-directory . up -d server ui
sleep 15
```

**Step 2: Verify health**

```bash
curl -s http://localhost:8001/healthz | python3 -m json.tool
curl -s -o /dev/null -w "UI: %{http_code}" http://localhost:4321/
```

**Step 3: Run UI tests**

```bash
cd ui && npx vitest run
```
Expected: 141 passing

**Step 4: Verify the new endpoint**

```bash
# Org geometry
curl -s "http://localhost:8001/v1/place/ltla24:E06000047/organisations/geometry?limit=5" | python3 -m json.tool | head -40

# Civil society profile with notable + cause areas
curl -s -X POST http://localhost:8001/v1/tools/get_civil_society_profile \
  -H "Content-Type: application/json" \
  -d '{"place_id": "ltla24:E06000047"}' | python3 -m json.tool | grep -E '"notable"|"oldest"|"largest"|"cause_area"|"income_concentration"'
```

**Step 5: Test the ask experience**

Set full consent and ask the question:

```bash
COOKIE_JAR=/tmp/cookies.txt
curl -s -c "$COOKIE_JAR" -X POST http://localhost:8001/v1/capture/consent \
  -H "Content-Type: application/json" -d '{"consent_level":"full"}' > /dev/null

time curl -s -b "$COOKIE_JAR" -X POST http://localhost:8001/v1/ask \
  -H "Content-Type: application/json" -H "Accept: text/event-stream" \
  -d '{"query":"How many charities are there in County Durham? Where are they? Who funds them?"}' \
  --max-time 120 | grep -E '"type"' | head -20
```

Expected: the SSE stream should include insight-callout blocks for notable orgs, a composition-chart for cause areas or top funders, a map block with organisations overlay, and an organisations block.

**Step 6: Invalidate answer cache**

Since the answer format has changed, clear cached answers so users get the new enriched format:

```bash
docker exec soundings-postgres-1 psql -U soundings -d soundings -c \
  "DELETE FROM cache.answer_cache;"
```

**Step 7: Commit any remaining changes**

```bash
git add -A
git commit -m "feat(civil-society): rebuild + verify enriched civil society profile"
```

---

## Summary of Changes

| Layer | What changes |
|-------|-------------|
| **Contracts** | `NotableOrgs` + `NotableOrg` + `CauseAreaCount` on `CivilSocietyProfile`; `date_of_registration` + `postcode` on `OrganisationRef` |
| **Orchestrator** | Query oldest/newest/largest + income concentration + cause-area aggregation in `compute_civil_society_profile`; surface reg date + postcode + operates_in in `_find_via_cc_loader` |
| **DB** | Migration 0007: `latitude` + `longitude` columns on `geography.postcode`; NSPL loader captures them; postcodes.io adapter captures them |
| **API** | New `GET /v1/place/{id}/organisations/geometry` GeoJSON endpoint |
| **Block schema** | `MapOverlay.source` expanded to `Literal["amenities", "organisations"]` |
| **UI renderer** | Org point layer on maps; founding year on org cards; funder + grants sections on CivilSocietyPanel |
| **System prompt** | Guidance for notable orgs (insight-callouts), cause-area composition chart, org map overlay |

# ONS NSPL Loader — Design Spec

> Status: approved design, ready for implementation planning.
> Date: 2026-07-07

## Goal

Populate `geography.postcode` from the ONS National Statistics Postcode Lookup
(NSPL) so postcode-based loaders (Companies House, Charity Commission) resolve
postcode → place in a single indexed DB lookup, instead of falling through to
the postcodes.io API. One authoritative bulk load replaces slow, rate-limited,
partial API warming.

## Background

`geography.postcode` maps a normalised postcode to eight geography place IDs
(`lsoa21`, `msoa21`, `ltla24`, `utla24`, `ward24`,
`westminster_constituency_24`, `region`, `country`), each foreign-keyed to
`geography.place.id`. The resolver (`soundings/adapters/postcodes_io/resolver.py`)
checks this table first and only batches the misses to postcodes.io.

Today the table holds ~961k rows, warmed incidentally by earlier Companies
House / FoE runs — and those rows carry **only** `ltla24`; the other seven
columns are NULL. Resolving the full UK postcode set cold via postcodes.io is
slow (100-at-a-time API calls over ~1M+ postcodes) and fragile (rate limits).
This was the "ONS NSPL pre-warm" item deferred in STATE; it is now on the
critical path for reliable Companies House loads.

NSPL relates both current and terminated postcodes to current statutory
geographies via best-fit allocation from 2021 Census Output Areas, issued
quarterly.

## Design decisions (locked)

| Decision | Choice |
|---|---|
| Source | Config-pinned ArcGIS item URL, follow redirects |
| Runner | Seed-runner (`--full`) + standalone `--once ons.nspl`; **not** a cron catalogue source |
| Coverage | All postcodes, including terminated (~2.7M rows) |
| Write strategy | Stream-decompress CSV → map columns → in-memory FK guard → batched `ON CONFLICT` upsert |
| `utla24` | Derived (no NSPL field): join `ltla24` → parent UTLA via `geography.place_hierarchy` |

## Source & configuration

Pinned to the current release, **NSPL May 2026**:

```
SOUNDINGS_NSPL_URL=https://www.arcgis.com/sharing/rest/content/items/7668e0d35cab4f6db6f15f03be610fb0/data
```

- Item `7668e0d35cab4f6db6f15f03be610fb0`, `NSPL_MAY_2026.zip`, 187,209,017 bytes
  (~178 MB), type "CSV Collection" (`application/zip`).
- The stable `/data` URL **302-redirects to a temporary signed S3 link**
  (~20 min expiry), so the HTTP client MUST follow redirects
  (`httpx ... follow_redirects=True`, matching `CompaniesHouseBulkClient`).
- Bumping to a later quarter (Aug 2026, …) is a one-line config change: swap the
  ArcGIS item ID. The item ID is discoverable via the ArcGIS search API
  (`.../sharing/rest/search?q=title:"National Statistics Postcode Lookup"
  type:"CSV Collection"&sortField=created&sortOrder=desc&f=json`).
- New setting `nspl_url: str` on `Settings` (`env_prefix="SOUNDINGS_"`), defaulting
  to the pinned URL above.

## Architecture & components

New adapter package `soundings/adapters/ons_nspl/`, following the existing
loader pattern (`companies_house`, `ons_geography`).

### `client.py` — `NsplBulkClient`
- Constructor: `http_client: httpx.AsyncClient | None`, `url: str`.
- `iter_rows() -> AsyncIterator[dict[str, str]]`: GET the URL following redirects,
  stream the response into a ZIP reader, locate the single data CSV member
  (`Data/*.csv` — the large postcode file, not the `Documents/` user guide),
  and yield each CSV row as a `{column: value}` dict via `csv.DictReader`.
- Streams rather than buffering: the ZIP body is read incrementally and the CSV
  member is decompressed on the fly, so the ~1 GB uncompressed CSV is never
  written to disk and never fully held in memory.
- Testable by injecting an in-memory ZIP (`urls`/bytes) exactly as the CH client
  tests inject fixture parts.

### `loader.py` — `NsplLoader(LoaderAdapter)`
- `source_id = "ons.nspl"`.
- Constructor mirrors `CompaniesHouseLoader`: `engine`, optional injected
  `client: NsplBulkClient | None`, optional `url` override. The default client is
  built in `load()` (not `__init__`) from the resolved URL — same lazy pattern
  applied in the CH `as_of` fix.
- `load()`:
  1. Fetch the valid place-ID set once: `SELECT id FROM geography.place` →
     `set[str]` (~45k prefixed IDs, a few MB).
  2. Stream rows via `client.iter_rows()`; map + FK-guard each row (pure helper,
     below); accumulate a batch (~10k rows) and flush via `ON CONFLICT (postcode)
     DO UPDATE`.
  3. After all rows are upserted, derive `utla24` with a single set-based UPDATE
     joining `geography.postcode.ltla24` to its parent UTLA in
     `geography.place_hierarchy` (exact hierarchy column names pinned in the
     implementation plan against the table schema).
  4. Return `LoaderResult(rows_written=<count>, notes=<summary of nulled/derived>)`.

### Row mapping (pure, unit-tested) — `_map_row(row, valid_ids) -> dict`

| `geography.postcode` column | NSPL field | Transform |
|---|---|---|
| `postcode` | `pcds` | `_normalise_postcode` (reuse from `postcodes_io.adapter`) |
| `lsoa21` | `lsoa21` | `"lsoa21:" + code` |
| `msoa21` | `msoa21` | `"msoa21:" + code` |
| `ltla24` | `laua` | `"ltla24:" + code` |
| `ward24` | `ward` | `"ward24:" + code` |
| `westminster_constituency_24` | `pcon` | `"westminster_constituency_24:" + code` |
| `region` | `rgn` | `"region:" + code` |
| `country` | `ctry` | `"country:" + code` |
| `utla24` | — | derived post-load (see above) |

**FK guard:** for each geography column, build the candidate prefixed ID and keep
it only if present in the valid place-ID set; otherwise set the column to `NULL`.
This makes any NSPL code we haven't seeded (a boundary-vintage mismatch, a
devolved-nation ward we don't hold) degrade to `NULL` instead of an FK violation.
Blank NSPL codes map to `NULL`.

> The exact NSPL header names above match recent NSPL vintages; they are
> re-confirmed against the pinned release's User Guide (item
> `17cf7c729ee54f7b8ec3d415ca4acb57`) when writing the plan, before any code that
> reads columns by name.

## Data flow

```
SOUNDINGS_NSPL_URL ──(GET, follow 302)──▶ signed S3 ZIP
        │ stream
        ▼
   ZIP reader ──▶ Data/*.csv (DictReader) ──▶ row dicts
        │
   _map_row + FK guard (valid place-ID set in memory)
        │  batch of ~10k
        ▼
  INSERT INTO geography.postcode ... ON CONFLICT (postcode) DO UPDATE
        │  (all rows upserted)
        ▼
  UPDATE ... SET utla24 = parent UTLA via place_hierarchy
```

## Placement, provenance, and runner wiring

- **Catalogue source**: add an `ons.nspl` entry to `catalogue/sources.yaml`
  (publisher ONS, licence OGL v3.0, `dataset_url` the geoportal NSPL page),
  `mode: loader`, **no `refresh_cadence`**. The catalogue-source loader daemon
  only schedules `mode='loader'` rows that have a cadence, so a null cadence means
  it is never auto-scheduled — but the source row exists so `data.loader_run`
  rows (which key on `source_id`) can be written.
- **Seed runner** (`soundings/seed/run.py`): run `NsplLoader` in the `--full`
  path (after the geography loaders that seed `geography.place`, since the FK
  guard depends on `geography.place` being populated). Skipped in `--light`
  (single-LTLA seed does not want 2.7M national postcodes).
- **On-demand**: register `ons.nspl → NsplLoader(engine).load()` in the loader
  daemon's `_loaders` map so `python -m soundings.loader.run --once ons.nspl`
  works.

## Error handling

- **Download / redirect failure**: propagate as a failed `LoaderResult` /
  exception; the seed-runner and daemon already record `data.loader_run` status
  `failed` with the error note.
- **Missing CSV member in ZIP**: raise a clear error naming the members found
  (guards against ONS changing the archive layout).
- **Unknown / blank geography codes**: nulled by the FK guard (not an error);
  counted and summarised in `LoaderResult.notes`.
- **Re-run safety**: `ON CONFLICT (postcode) DO UPDATE` makes the load idempotent;
  NSPL is authoritative and overwrites the partial postcodes.io-warmed values.
  (A stale postcode that vanished from NSPL is not deleted — acceptable; terminated
  postcodes are retained by design, and true deletions are vanishingly rare.)

## Testing

- **Pure unit** (no DB, no network):
  - `_map_row`: correct NSPL→column mapping and prefixing; `_normalise_postcode`
    applied to `pcds`; blank codes → `NULL`.
  - FK guard: a code absent from the valid-ID set → `NULL`; a present code kept.
- **Client unit**: `iter_rows` over a small in-memory ZIP containing a fixture
  `Data/x.csv` yields the expected row dicts; a ZIP with no data CSV raises.
- **Integration** (DB-marked, like `test_companies_house_loader` integration):
  seed a handful of `geography.place` rows (a couple of LTLAs + their UTLA parents
  in `place_hierarchy`, an LSOA, a region, a country) and a tiny fixture CSV;
  run the loader; assert rows upserted with correctly prefixed IDs, unknown codes
  nulled, and `utla24` derived from `place_hierarchy`.
- **No live download in tests** — the ~178 MB fetch is never exercised in CI; a
  separate `live`-marked smoke test (opt-in) may assert the pinned URL still
  serves a ZIP, mirroring `test_companies_house_live`.

## Out of scope

- Auto-discovery of the latest NSPL release (config bump is deliberate).
- Loading NSPL fields beyond the eight `geography.postcode` columns (grid refs,
  health geographies, IMD, etc.).
- Deleting postcodes that disappear between NSPL vintages.
- A cron schedule (on-demand only, per the locked decisions).

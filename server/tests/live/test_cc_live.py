"""Live test for the Charity Commission bulk register download + parser.

Marker `live` — runs nightly, not in PR CI. No API key required;
the bulk download is anonymous.

Scope: verify the real `publicextract.charity.zip` URL is alive AND
the file format still matches what `CharityCommissionBulkClient`
expects (column names, tab delimiter, status / linked_charity_number
semantics). DB writes + postcode resolution + indicator aggregation
are exercised by mock-transport unit tests; we don't redo them here
because a cold-cache full load is dominated by ~220k postcodes.io
batch lookups and runs for ~5–10 min, which is too slow for a
single-source live test.

`xfail` cleanly on upstream slowness or 5xx — flaky CC shouldn't
blank the nightly suite.
"""

import asyncio
from typing import Any

import pytest

from soundings.adapters.charity_commission.client import CharityCommissionBulkClient

pytestmark = [pytest.mark.live, pytest.mark.integration]


async def test_cc_bulk_download_parses_into_charity_dicts() -> None:
    client = CharityCommissionBulkClient()

    rows: list[dict[str, Any]] = []
    sample_limit = 50_000  # Way below the ~170k real population.
    try:
        # 120s is enough for the download + first 50k rows on a normal day.
        async def _collect() -> None:
            async for row in client.iter_active_charities():
                rows.append(row)
                if len(rows) >= sample_limit:
                    break

        await asyncio.wait_for(_collect(), timeout=120)
    except TimeoutError as e:
        pytest.xfail(f"CC bulk download / parse > 120s — likely upstream flake: {e}")

    assert len(rows) >= sample_limit, (
        f"expected at least {sample_limit} rows, got {len(rows)} — "
        "schema or filtering likely drifted"
    )

    sample = rows[0]
    assert sample["registration_number"]
    assert sample["status"] == "Registered"
    assert isinstance(sample["classification"], list)

    # Real-world sanity: somewhere in the first 50k rows we should see
    # a UK postcode (CC publishes some non-UK ones; we just want
    # evidence that the postcode column wired through).
    uk_postcodes = [r for r in rows if r["postcode"] and r["postcode"][0].isalpha()]
    assert uk_postcodes, "no UK-shaped postcodes in the first 50k rows"

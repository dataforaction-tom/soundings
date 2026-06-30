"""Live smoke test for the Companies House bulk product.

Nightly only (`@pytest.mark.live`). Verifies the bulk URL is alive and the
streaming parser handles the real CSV schema — reads just the first slice
of one part file, never the full ~5M-row ingest (per the CC live-test
lesson: keep live tests fast and scoped to "URL alive + schema parses").
"""

from datetime import date, timedelta

import httpx
import pytest

from soundings.adapters.companies_house.client import CompaniesHouseBulkClient, bulk_part_urls

pytestmark = pytest.mark.live

SAMPLE_LIMIT = 500


def _live_part_url() -> str:
    """Return a part-1 URL that exists. The product is dated YYYY-MM-01 and
    published within ~5 working days of month end, so early in a month the
    current-month file may not exist yet — fall back to the previous month."""
    today = date.today()
    prev_month_end = today.replace(day=1) - timedelta(days=1)
    for candidate in (bulk_part_urls(today)[0], bulk_part_urls(prev_month_end)[0]):
        resp = httpx.head(candidate, follow_redirects=True, timeout=60.0)
        if resp.status_code == 200:
            return candidate
    raise AssertionError("No live Companies House bulk part URL found for this or last month")


async def test_bulk_product_alive_and_schema_parses() -> None:
    url = _live_part_url()
    client = CompaniesHouseBulkClient(urls=[url])

    sample: list[dict[str, object]] = []
    async for company in client.iter_active_companies():
        sample.append(company)
        if len(sample) >= SAMPLE_LIMIT:
            break

    assert sample, "expected at least one active company in the bulk part"
    # Schema sanity: stable keys present, statuses filtered, numbers populated.
    for company in sample:
        assert company["status"] == "Active"
        assert company["company_number"]
        assert "postcode" in company
        assert "sic_codes" in company
    # The registered-office postcode column must actually populate for most rows.
    with_postcode = sum(1 for c in sample if c["postcode"])
    assert with_postcode > len(sample) * 0.5

"""Live test for the Find That Charity API.

Marker `live` — runs nightly, not in PR CI. No API key required;
api.findthatcharity.uk is public.

Scope: verify the search endpoint is alive and returns expected
response shape. Using SC005336 (Volunteer Scotland) as a known-stable
test subject.
"""

import pytest

from soundings.adapters.find_that_charity.client import FindThatCharityClient

pytestmark = pytest.mark.live


async def test_search_scotland_returns_volunteer_scotland() -> None:
    """SC005336 is Volunteer Scotland - verify basic search works."""
    client = FindThatCharityClient()
    results = await client.search(country="Scotland", limit=10)

    assert len(results) > 0, "no results returned for Scotland search"

    # Find SC005336 in results
    sc_ids = [r.id for r in results if r.id == "SC005336"]
    assert len(sc_ids) > 0, "SC005336 (Volunteer Scotland) not found in Scotland results"

    result = next(r for r in results if r.id == "SC005336")
    assert result.name == "Volunteer Scotland"
    assert result.country == "Scotland"


async def test_get_charity_returns_volunteer_scotland_details() -> None:
    """Direct lookup of SC005336."""
    client = FindThatCharityClient()
    result = await client.get_charity("SC005336")

    assert result is not None, "no result returned for SC005336"
    assert result.id == "SC005336"
    assert result.name == "Volunteer Scotland"
    assert result.country == "Scotland"
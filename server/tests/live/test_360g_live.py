"""Live test for the 360Giving Datastore API.

Marker `live` — runs nightly, not in PR CI. No API key required;
api.threesixtygiving.org is public.

Scope: verify the org + grants_received endpoints are alive and the
response shape matches `ThreeSixtyGivingClient`'s expectations. We
use Oxfam (GB-CHC-202918) as a known-stable test subject — it's been
in the register since 1965, has consistent grant activity, and is
unlikely to disappear.

We don't run the adapter end-to-end against real data here because
that would require the CC loader to have populated data.organisation
first (and the postcodes.io spine to know about Oxfam's postcode).
Adapter-level integration is the unit test's job.
"""

import pytest

from soundings.adapters.threesixtygiving.client import ThreeSixtyGivingClient

pytestmark = [pytest.mark.live, pytest.mark.integration]


async def test_get_org_aggregate_returns_oxfam_lifetime_stats() -> None:
    client = ThreeSixtyGivingClient()
    aggregate = await client.get_org_aggregate("GB-CHC-202918")
    assert aggregate is not None, "no aggregate returned for Oxfam (GB-CHC-202918)"
    assert aggregate.grants > 0
    assert aggregate.total_gbp > 0
    assert aggregate.latest_grant_date is not None
    assert len(aggregate.latest_grant_date) >= 10
    assert aggregate.latest_grant_date[4] == "-"
    assert aggregate.latest_grant_date[7] == "-"


async def test_iter_grants_received_yields_at_least_one_oxfam_grant() -> None:
    client = ThreeSixtyGivingClient()
    grants = []
    async for grant in client.iter_grants_received("GB-CHC-202918", page_size=5):
        grants.append(grant)
        if len(grants) >= 3:
            break
    assert len(grants) >= 1, "no grants_received returned for Oxfam"
    sample = grants[0]
    data = sample.get("data") or {}
    assert data.get("awardDate"), "awardDate missing from grant payload"
    assert data.get("amountAwarded") is not None
    assert data.get("currency"), "currency missing from grant payload"

"""Tests for the Phase 4 extension of PassthroughAdapter.

Two optional methods land on the base class so subclasses can opt in
without forcing existing adapters to implement them:

- `fetch_organisations(place_id, filters=None, limit=50)` — returns a
  list of OrganisationRef. Default returns []; CC + FTC override.
- `pre_warm_for_places(place_ids)` — best-effort cache warmer. Default
  no-op; CC + 360G override to fan out their indicator counts ahead of
  user-facing reads.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.contracts.organisation import OrganisationRef
from soundings.contracts.source_ref import SourceRef
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


def _ref() -> SourceRef:
    return SourceRef(
        source_id="test.passthrough.fixture",
        source_label="test",
        publisher="test",
        retrieved_at=datetime.now(tz=UTC),
        cache_status="cached",
        licence="CC0",
    )


class _BareAdapter(PassthroughAdapter):
    source_id = "test.passthrough.bare"

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any:
        del client, cache_key
        return None


class _OrgAdapter(PassthroughAdapter):
    source_id = "test.passthrough.orgs"

    def __init__(self) -> None:
        super().__init__(get_engine(), ttl=timedelta(hours=1))
        self.warm_calls: list[list[str]] = []

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any:
        del client, cache_key
        return None

    async def fetch_organisations(
        self,
        place_id: str,
        filters: list[str] | None = None,
        limit: int = 50,
    ) -> list[OrganisationRef]:
        del filters, limit
        return [
            OrganisationRef(
                id="charity_commission:1",
                name=f"Test Org for {place_id}",
                classification=["test"],
                registered_address_place_id=place_id,
                operates_in_place_ids=[place_id],
                recent_grants=[],
                source=_ref(),
            )
        ]

    async def pre_warm_for_places(self, place_ids: list[str]) -> None:
        self.warm_calls.append(list(place_ids))


async def test_bare_adapter_returns_empty_organisations() -> None:
    adapter = _BareAdapter(get_engine(), ttl=timedelta(hours=1))
    out = await adapter.fetch_organisations("ltla24:E06000004")
    assert out == []


async def test_bare_adapter_pre_warm_is_a_noop() -> None:
    adapter = _BareAdapter(get_engine(), ttl=timedelta(hours=1))
    # Must not raise even with a large slate of places.
    await adapter.pre_warm_for_places(["ltla24:A", "ltla24:B"])


async def test_overriding_subclass_returns_organisations() -> None:
    adapter = _OrgAdapter()
    out = await adapter.fetch_organisations("ltla24:E06000004", limit=10)
    assert len(out) == 1
    assert out[0].name == "Test Org for ltla24:E06000004"
    assert out[0].registered_address_place_id == "ltla24:E06000004"


async def test_overriding_subclass_records_pre_warm() -> None:
    adapter = _OrgAdapter()
    await adapter.pre_warm_for_places(["ltla24:A", "ltla24:B"])
    assert adapter.warm_calls == [["ltla24:A", "ltla24:B"]]


async def test_pre_warm_swallows_exceptions_from_overrides() -> None:
    """A misbehaving override shouldn't poison the daemon loop. The base
    contract is best-effort: callers (the pre_warmer daemon) get a
    success even when the underlying adapter explodes."""

    class _AngryAdapter(PassthroughAdapter):
        source_id = "test.passthrough.angry"

        async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any:
            del client, cache_key
            return None

        async def pre_warm_for_places(self, place_ids: list[str]) -> None:
            del place_ids
            raise RuntimeError("upstream is on fire")

    adapter = _AngryAdapter(get_engine(), ttl=timedelta(hours=1))
    # The default contract wraps the call in a try/except — the daemon's
    # safety net. We invoke via the public entry point on the base, not
    # the override, so callers can trust it to not raise.
    await adapter.safe_pre_warm(["ltla24:A"])

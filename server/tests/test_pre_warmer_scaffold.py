"""Tests for the pre_warmer daemon scaffold.

The daemon iterates passthrough adapters that override
`pre_warm_for_places`, calls `safe_pre_warm(<LTLA place_ids>)` on each,
and reschedules per the catalogue.source refresh_cadence cron.

These tests exercise the registry-walk + LTLA-list lookup directly,
mocking out the APScheduler machinery (which is a thin shell around
asyncio).
"""

from typing import Any

import httpx
import pytest
from sqlalchemy import text

from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.db.engine import get_engine
from soundings.orchestration.registry import AdapterRegistry
from soundings.pre_warmer.run import (
    fetch_place_ids_for_warming,
    run_pre_warm_once,
)

pytestmark = pytest.mark.integration


class _WarmingAdapter(PassthroughAdapter):
    source_id = "test.prewarm.fixture"

    def __init__(self, engine: Any) -> None:
        from datetime import timedelta

        super().__init__(engine, ttl=timedelta(hours=24))
        self.warm_calls: list[list[str]] = []

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any:
        del client, cache_key
        return None

    async def pre_warm_for_places(self, place_ids: list[str]) -> None:
        self.warm_calls.append(list(place_ids))


class _AngryWarmer(PassthroughAdapter):
    source_id = "test.prewarm.angry"

    def __init__(self, engine: Any) -> None:
        from datetime import timedelta

        super().__init__(engine, ttl=timedelta(hours=24))

    async def _call_upstream(self, client: httpx.AsyncClient, cache_key: str) -> Any:
        del client, cache_key
        return None

    async def pre_warm_for_places(self, place_ids: list[str]) -> None:
        del place_ids
        raise RuntimeError("upstream is on fire")


async def _seed_ltla_places(codes: list[str]) -> list[str]:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM data.indicator_value"))
        await conn.execute(text("DELETE FROM data.trend_point"))
        await conn.execute(text("DELETE FROM geography.postcode"))
        await conn.execute(text("DELETE FROM geography.place_hierarchy"))
        await conn.execute(text("DELETE FROM geography.place"))
        place_ids: list[str] = []
        for code in codes:
            pid = f"ltla24:{code}"
            place_ids.append(pid)
            await conn.execute(
                text(
                    "INSERT INTO geography.place (id, type, code, name) "
                    "VALUES (:id, 'ltla24', :code, :name)"
                ),
                {"id": pid, "code": code, "name": f"Place {code}"},
            )
    return place_ids


async def test_fetch_place_ids_for_warming_returns_ltla_universe() -> None:
    expected = await _seed_ltla_places(["E06000004", "E08000001", "E08000002"])
    engine = get_engine()
    place_ids = await fetch_place_ids_for_warming(engine)
    assert sorted(place_ids) == sorted(expected)


async def test_run_pre_warm_once_invokes_overriding_adapter() -> None:
    place_ids = await _seed_ltla_places(["E06000004", "E06000001"])
    engine = get_engine()
    registry = AdapterRegistry(engine)
    adapter = _WarmingAdapter(engine)
    registry.register(_WarmingAdapter.source_id, lambda eng: adapter)

    rc = await run_pre_warm_once(engine, registry, [_WarmingAdapter.source_id])
    assert rc == 0
    assert adapter.warm_calls == [sorted(place_ids)]


async def test_run_pre_warm_once_swallows_misbehaving_adapter() -> None:
    """Per the base class' safe_pre_warm contract — the daemon's loop
    keeps going when one adapter raises."""
    await _seed_ltla_places(["E06000004"])
    engine = get_engine()
    registry = AdapterRegistry(engine)
    angry = _AngryWarmer(engine)
    happy = _WarmingAdapter(engine)
    registry.register(_AngryWarmer.source_id, lambda eng: angry)
    registry.register(_WarmingAdapter.source_id, lambda eng: happy)

    rc = await run_pre_warm_once(
        engine, registry, [_AngryWarmer.source_id, _WarmingAdapter.source_id]
    )
    # Returns 0 even with one failure — best-effort by contract.
    assert rc == 0
    # The happy adapter still got its turn.
    assert happy.warm_calls == [["ltla24:E06000004"]]


async def test_run_pre_warm_once_unknown_source_returns_nonzero() -> None:
    await _seed_ltla_places(["E06000004"])
    engine = get_engine()
    registry = AdapterRegistry(engine)
    rc = await run_pre_warm_once(engine, registry, ["unknown.source"])
    assert rc != 0

from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from soundings.adapters.passthrough_base import PassthroughAdapter
from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.source_ref import SourceRef
from soundings.db.engine import get_engine

pytestmark = pytest.mark.integration


class _StubAdapter(PassthroughAdapter):
    source_id = "test.passthrough.stub"
    upstream_calls = 0

    async def _call_upstream(
        self, client: httpx.AsyncClient, cache_key: str
    ) -> Any | None:
        type(self).upstream_calls += 1
        return {"value": 42, "cache_key": cache_key}

    def _materialise(
        self,
        payload: Any,
        indicator_key: str,
        place_id: str,
        period: str | None,
        source_ref: SourceRef,
    ) -> IndicatorValue | None:
        return IndicatorValue(
            place_id=place_id,
            indicator=indicator_key,
            value=float(payload["value"]),
            unit="things",
            period=period or "latest",
            source=source_ref,
            confidence="experimental",
        )


async def _ensure_source() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM cache.source_cache WHERE source_id = 'test.passthrough.stub'"))
        await conn.execute(
            text(
                "INSERT INTO catalogue.source "
                "(id, label, publisher, licence, mode, rate_limit) "
                "VALUES ('test.passthrough.stub', 'Stub', 'Test', 'CC0', 'passthrough', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )


async def test_passthrough_fetch_indicator_marks_live_then_cached() -> None:
    engine = get_engine()
    await _ensure_source()
    _StubAdapter.upstream_calls = 0
    adapter = _StubAdapter(engine, ttl=timedelta(hours=1))

    iv1 = await adapter.fetch_indicator("test.indicator", "ltla24:E06000004", None)
    assert iv1 is not None
    assert iv1.value == 42
    assert iv1.source.cache_status == "live"
    assert _StubAdapter.upstream_calls == 1

    iv2 = await adapter.fetch_indicator("test.indicator", "ltla24:E06000004", None)
    assert iv2 is not None
    assert iv2.source.cache_status == "cached"
    assert _StubAdapter.upstream_calls == 1  # second call hit cache, no upstream

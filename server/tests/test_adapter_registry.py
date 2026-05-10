import pytest
from sqlalchemy import text

from soundings.adapters.base import LoaderAdapter, LoaderResult
from soundings.db.engine import get_engine
from soundings.orchestration.errors import IndicatorNotRegisteredError
from soundings.orchestration.registry import AdapterRegistry

pytestmark = pytest.mark.integration


class _Stub(LoaderAdapter):
    source_id = "test.registry.stub"

    async def load(self, run_id: str | None = None) -> LoaderResult:
        return LoaderResult(rows_written=0)


async def _ensure_indicator_for(source_id: str, indicator_key: str) -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO catalogue.source "
                "(id, label, publisher, licence, mode, rate_limit) "
                "VALUES (:sid, 'Stub', 'Test', 'CC0', 'loader', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"sid": source_id},
        )
        await conn.execute(
            text(
                "INSERT INTO catalogue.indicator "
                "(key, label, unit, source_id, available_at, caveats, related_keys) "
                "VALUES (:k, 'Stub', 'unit', :sid, ARRAY['ltla24']::varchar[], '[]'::jsonb, ARRAY[]::varchar[]) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"k": indicator_key, "sid": source_id},
        )


async def test_registry_resolves_adapter_via_indicator_catalogue() -> None:
    engine = get_engine()
    await _ensure_indicator_for("test.registry.stub", "test.indicator.foo")

    registry = AdapterRegistry(engine)
    registry.register("test.registry.stub", lambda eng: _Stub(eng))

    adapter = await registry.adapter_for_indicator("test.indicator.foo")
    assert isinstance(adapter, _Stub)

    # Caches the constructed adapter.
    again = await registry.adapter_for_indicator("test.indicator.foo")
    assert again is adapter


async def test_registry_raises_for_unknown_indicator() -> None:
    engine = get_engine()
    registry = AdapterRegistry(engine)
    with pytest.raises(IndicatorNotRegisteredError):
        await registry.adapter_for_indicator("test.indicator.never.registered")

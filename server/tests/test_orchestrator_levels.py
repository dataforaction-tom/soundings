from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from soundings.adapters.base import LoaderAdapter, LoaderResult
from soundings.contracts.indicator_value import IndicatorValue
from soundings.contracts.source_ref import SourceRef
from soundings.db.engine import get_engine
from soundings.orchestration.orchestrator import IndicatorOrchestrator
from soundings.orchestration.registry import AdapterRegistry

pytestmark = pytest.mark.integration


class _Echo(LoaderAdapter):
    source_id = "test.levels.echo"

    async def load(self, run_id: str | None = None) -> LoaderResult:
        return LoaderResult(rows_written=0)

    async def fetch_indicator(
        self, indicator_key: str, place_id: str, period: str | None
    ) -> IndicatorValue | None:
        return IndicatorValue(
            place_id=place_id,
            indicator=indicator_key,
            value=1,
            unit="x",
            period="1",
            source=SourceRef(
                source_id=self.source_id,
                source_label="echo",
                publisher="t",
                retrieved_at=datetime.now(tz=UTC),
                cache_status="cached",
                licence="CC0",
            ),
            confidence="official",
        )


async def test_orchestrator_refuses_indicator_at_unsupported_level() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO catalogue.source "
                "(id, label, publisher, licence, mode, rate_limit) "
                "VALUES ('test.levels.echo', 'echo', 't', 'CC0', 'loader', '{}'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO catalogue.indicator "
                "(key, label, unit, source_id, available_at, caveats, related_keys) "
                "VALUES ('test.levels.lsoa_only', 'echo', 'x', 'test.levels.echo', "
                "ARRAY['lsoa21']::varchar[], '[]'::jsonb, ARRAY[]::varchar[]) "
                "ON CONFLICT (key) DO UPDATE SET available_at = EXCLUDED.available_at"
            )
        )

    registry = AdapterRegistry(engine)
    registry.register("test.levels.echo", lambda eng: _Echo(eng))
    orchestrator = IndicatorOrchestrator(engine, registry)

    # Asking at country level when the indicator is only available at LSOA.
    result = await orchestrator.fetch(
        indicator_keys=["test.levels.lsoa_only"],
        place_id="country:E92000001",
        period=None,
    )
    assert result.values == []
    assert result.partial is True
    assert any(
        "INDICATOR_NOT_AVAILABLE_AT_LEVEL" in c or "not published at" in c for c in result.caveats
    )

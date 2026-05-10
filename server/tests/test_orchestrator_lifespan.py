import pytest

from soundings.app import app
from soundings.orchestration.orchestrator import IndicatorOrchestrator
from soundings.orchestration.registry import AdapterRegistry

pytestmark = pytest.mark.integration


async def test_lifespan_constructs_registry_and_orchestrator_on_app_state() -> None:
    async with app.router.lifespan_context(app):
        registry = app.state.adapter_registry
        orchestrator = app.state.orchestrator

    assert isinstance(registry, AdapterRegistry)
    assert isinstance(orchestrator, IndicatorOrchestrator)


async def test_lifespan_registers_phase_1_adapters() -> None:
    async with app.router.lifespan_context(app):
        registry = app.state.adapter_registry
        for source_id in (
            "ons.mid_year_estimates",
            "ons.census2021",
            "mhclg.imd2025",
        ):
            adapter = registry.adapter_for_source(source_id)
            assert adapter.source_id == source_id

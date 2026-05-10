from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from soundings.adapters.mhclg_imd2025.adapter import MhclgImd2025Adapter
from soundings.adapters.ons_census2021.adapter import OnsCensus2021Adapter
from soundings.adapters.ons_mid_year_estimates.adapter import OnsMidYearEstimatesAdapter
from soundings.catalogue.loader import load_catalogue_into_db
from soundings.db.engine import get_engine
from soundings.http.health import router as health_router
from soundings.orchestration.orchestrator import IndicatorOrchestrator
from soundings.orchestration.registry import AdapterRegistry

CATALOGUE_DIR = Path(__file__).resolve().parent.parent.parent / "catalogue"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    await load_catalogue_into_db(
        engine,
        sources_path=CATALOGUE_DIR / "sources.yaml",
        indicators_path=CATALOGUE_DIR / "indicators.yaml",
    )

    registry = AdapterRegistry(engine)
    registry.register("ons.mid_year_estimates", OnsMidYearEstimatesAdapter)
    registry.register("ons.census2021", OnsCensus2021Adapter)
    registry.register("mhclg.imd2025", MhclgImd2025Adapter)

    app.state.adapter_registry = registry
    app.state.orchestrator = IndicatorOrchestrator(engine, registry)

    yield


app = FastAPI(title="Soundings", version="0.0.1", lifespan=lifespan)
app.include_router(health_router)

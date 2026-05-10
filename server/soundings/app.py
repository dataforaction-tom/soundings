from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI

from soundings.adapters.mhclg_imd2025.adapter import MhclgImd2025Adapter
from soundings.adapters.ons_census2021.adapter import OnsCensus2021Adapter
from soundings.adapters.ons_mid_year_estimates.adapter import OnsMidYearEstimatesAdapter
from soundings.adapters.postcodes_io.adapter import PostcodesIoAdapter
from soundings.catalogue.loader import load_catalogue_into_db
from soundings.db.engine import get_engine
from soundings.geography.service import GeographyService
from soundings.http.catalogue import router as catalogue_router
from soundings.http.errors import install_error_envelope
from soundings.http.health import router as health_router
from soundings.http.sources import router as sources_router
from soundings.http.tools import router as tools_router
from soundings.orchestration.orchestrator import IndicatorOrchestrator
from soundings.orchestration.registry import AdapterRegistry

CATALOGUE_DIR = Path(__file__).resolve().parent.parent.parent / "catalogue"
POSTCODES_IO_TTL = timedelta(hours=720)


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

    postcodes_io = PostcodesIoAdapter(engine, ttl=POSTCODES_IO_TTL)

    app.state.engine = engine
    app.state.adapter_registry = registry
    app.state.orchestrator = IndicatorOrchestrator(engine, registry)
    app.state.geography_service = GeographyService(engine, postcodes_io)

    yield


app = FastAPI(title="Soundings", version="0.0.1", lifespan=lifespan)
app.include_router(health_router)
app.include_router(tools_router)
app.include_router(sources_router)
app.include_router(catalogue_router)
install_error_envelope(app)

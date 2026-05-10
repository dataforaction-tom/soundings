from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from soundings.catalogue.loader import load_catalogue_into_db
from soundings.db.engine import get_engine
from soundings.http.health import router as health_router

CATALOGUE_DIR = Path(__file__).resolve().parent.parent.parent / "catalogue"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await load_catalogue_into_db(
        get_engine(),
        sources_path=CATALOGUE_DIR / "sources.yaml",
        indicators_path=CATALOGUE_DIR / "indicators.yaml",
    )
    yield


app = FastAPI(title="Soundings", version="0.0.1", lifespan=lifespan)
app.include_router(health_router)

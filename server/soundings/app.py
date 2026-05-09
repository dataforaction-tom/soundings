from fastapi import FastAPI

from soundings.http.health import router as health_router

app = FastAPI(title="Soundings", version="0.0.1")
app.include_router(health_router)

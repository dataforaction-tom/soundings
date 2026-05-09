from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from soundings.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        str(settings.database_url),
        pool_size=10,
        max_overflow=5,
        pool_pre_ping=True,
    )

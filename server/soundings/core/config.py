import os
from functools import lru_cache

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOUNDINGS_", env_file=None)

    database_url: PostgresDsn = (
        "postgresql+asyncpg://soundings:changeme-locally@localhost:5433/soundings"  # type: ignore[assignment]
    )
    log_level: str = "info"
    env: str = "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    if "DATABASE_URL" in os.environ:
        return Settings(database_url=os.environ["DATABASE_URL"])
    return Settings()

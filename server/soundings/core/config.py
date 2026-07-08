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
    ui_origin: str = "http://localhost:8088"
    anthropic_api_key: str = ""
    ask_model: str = "claude-sonnet-5"
    # ONS NSPL bulk ZIP (stable ArcGIS item /data URL; redirects to a signed
    # S3 link). Pinned to the current quarterly release — bump the item ID when
    # ONS republishes. See docs/superpowers/specs/2026-07-07-nspl-loader-design.md.
    nspl_url: str = (
        "https://www.arcgis.com/sharing/rest/content/items/7668e0d35cab4f6db6f15f03be610fb0/data"
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    if "DATABASE_URL" in os.environ:
        return Settings(database_url=os.environ["DATABASE_URL"])
    return Settings()

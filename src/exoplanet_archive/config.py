from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://exoplanet:exoplanet@localhost:5432/exoplanet"
    log_level: str = "INFO"

    tap_url: str = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
    tap_timeout_seconds: float = 120.0

    # Safety limits: a snapshot outside these is treated as a bad upstream response.
    ingest_min_row_ratio: float = 0.9
    ingest_max_reject_ratio: float = 0.01


@lru_cache
def get_settings() -> Settings:
    return Settings()

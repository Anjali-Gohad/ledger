"""
Central configuration. Everything env-driven so the same image runs
locally, in Docker Compose, and (later) wherever this gets deployed —
no hardcoded hosts anywhere else in the codebase.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Default points at localhost so `uvicorn app.main:app` works
    # straight off the host during local dev without Docker.
    database_url: str = "postgresql+asyncpg://ledger:ledger@localhost:5432/ledger"
    redis_url: str = "redis://localhost:6379/0"

    # Pool sizing: kept small deliberately. This is a queue system —
    # most DB work is short transactions (insert job, update status),
    # not long-held connections. Oversized pools just move the
    # bottleneck to Postgres's own connection limit.
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_pool_timeout_seconds: int = 30
    # Recycle connections periodically so we never hand out one that
    # a middlebox or Postgres itself has silently killed.
    db_pool_recycle_seconds: int = 1800

    lock_ttl_seconds: int = 60
    lock_renewal_interval_seconds: int = 20


settings = Settings()

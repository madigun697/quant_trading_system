from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_db: str = Field(default="quant", alias="POSTGRES_DB")
    postgres_user: str = Field(default="quant", alias="POSTGRES_USER")
    postgres_password: str = Field(default="quant", alias="POSTGRES_PASSWORD")
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")

    minio_root_user: str = Field(default="minioadmin", alias="MINIO_ROOT_USER")
    minio_root_password: str = Field(default="minioadmin", alias="MINIO_ROOT_PASSWORD")
    minio_endpoint: str = Field(default="http://localhost:9000", alias="MINIO_ENDPOINT")
    minio_region: str = Field(default="us-east-1", alias="MINIO_REGION")

    alphavantage_api_key: str | None = Field(default=None, alias="ALPHAVANTAGE_API_KEY")
    tiingo_api_key: str | None = Field(default=None, alias="TIINGO_API_KEY")
    fred_api_key: str | None = Field(default=None, alias="FRED_API_KEY")
    sec_user_agent: str | None = Field(default=None, alias="SEC_USER_AGENT")

    prototype_cohort: str = Field(default="prototype", alias="PROTOTYPE_COHORT")
    default_cohort: str = Field(default="us_liquidity_700_v1", alias="DEFAULT_COHORT")
    universe_buffer_cohort: str = Field(default="us_liquidity_900_buffer_v1", alias="UNIVERSE_BUFFER_COHORT")
    universe_buffer_size: int = Field(default=900, alias="UNIVERSE_BUFFER_SIZE")
    universe_target_size: int = Field(default=700, alias="UNIVERSE_TARGET_SIZE")
    liquidity_lookback_days: int = Field(default=60, alias="LIQUIDITY_LOOKBACK_DAYS")
    liquidity_discovery_days: int = Field(default=90, alias="LIQUIDITY_DISCOVERY_DAYS")
    tiingo_hourly_request_budget: int = Field(default=50, alias="TIINGO_HOURLY_REQUEST_BUDGET")
    tiingo_monthly_request_budget: int = Field(default=1000, alias="TIINGO_MONTHLY_REQUEST_BUDGET")
    tiingo_discovery_batch_size: int = Field(default=200, alias="TIINGO_DISCOVERY_BATCH_SIZE")
    yfinance_batch_size: int = Field(default=100, alias="YFINANCE_BATCH_SIZE")
    sec_daily_request_budget: int = Field(default=50, alias="SEC_DAILY_REQUEST_BUDGET")
    yfinance_timeout_seconds: float = Field(default=30.0, alias="YFINANCE_TIMEOUT_SECONDS")
    alpha_vantage_throttle_seconds: float = Field(default=15.0, alias="ALPHA_VANTAGE_THROTTLE_SECONDS")
    tiingo_throttle_seconds: float = Field(default=1.0, alias="TIINGO_THROTTLE_SECONDS")

    @property
    def postgres_dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user} password={self.postgres_password}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

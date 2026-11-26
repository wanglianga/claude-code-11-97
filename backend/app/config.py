from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CLM_", extra="ignore")

    database_url: str = "postgresql+psycopg2://ccdev:ccdev@127.0.0.1:5432/ccdev"
    # 支付网关模拟：初始响应延迟（秒），用于模拟“稍后查询”
    gateway_delay_seconds: int = 0
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080"


@lru_cache
def get_settings() -> Settings:
    return Settings()

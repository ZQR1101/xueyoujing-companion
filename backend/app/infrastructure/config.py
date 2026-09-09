"""环境配置加载。

读取项目根目录的 .env（样例见 .env.example）；本地 .env 不提交。
字段属拟定方案，在 T02/T07 实施时按规格书最终确定。
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_dev_url: str = "http://localhost:5174"

    database_url: str = "sqlite:///./data/app.db"

    # 复习间隔基线（§7.2：完成后 1 天，可配置）
    review_interval_days: int = 1

    llm_provider: str = "mock"
    llm_model_id: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_timeout_seconds: int = 30

    demo_token_secret: str = "change-me-in-local-env"


@lru_cache
def get_settings() -> Settings:
    return Settings()

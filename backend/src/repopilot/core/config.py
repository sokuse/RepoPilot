from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="REPOPILOT_",
        extra="ignore",
    )

    app_name: str = "RepoPilot API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173"]
    database_url: str = "sqlite:///./repopilot.db"
    repository_storage_path: Path = BACKEND_DIR / "data" / "repositories"
    git_clone_timeout_seconds: int = 300
    git_clone_attempts: int = 3
    git_retry_base_delay_seconds: float = 1.0
    git_proxy_url: str | None = None
    max_scanned_file_size_bytes: int = 1_000_000
    chunk_size_chars: int = 1_500
    chunk_overlap_chars: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

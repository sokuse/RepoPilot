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
    vector_database_path: Path = BACKEND_DIR / "data" / "qdrant"
    embedding_model_name: str = "text-embedding-v4"
    embedding_api_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # Embedding 与聊天模型都属于百炼 Qwen 服务，共用同一个 API Key。
    qwen_api_key: str | None = None
    embedding_dimensions: int = 1_024
    vector_collection_name: str = "repopilot_chunks"
    embedding_batch_size: int = 10
    chat_model_name: str = "qwen-plus"
    rag_retrieval_limit: int = 8
    rag_max_context_chars: int = 16_000
    rag_temperature: float = 0.1

@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    model_provider: Literal["dashscope", "mock"] = "dashscope"
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    chat_model: str = "qwen-plus"
    embedding_model: str = "text-embedding-v4"
    embedding_dim: int = 1024
    embed_batch_size: int = 10

    postgres_dsn: str = "postgresql://agent:agent@db:5432/agentlab"
    redis_url: str = "redis://redis:6379/0"
    memory_backend: Literal["redis", "memory"] = "redis"
    session_ttl_seconds: int = 86400
    max_history_messages: int = 12

    rag_top_k: int = 5
    rag_score_threshold: float = 0.30
    ingest_on_startup: bool = True
    corpus_dir: str = "data/corpus"
    demo_dir: str = "demo"

    max_message_chars: int = 2000
    log_level: str = "INFO"

    @property
    def is_mock(self) -> bool:
        return self.model_provider == "mock"

    def validate_runtime(self) -> None:
        if not self.is_mock and not self.dashscope_api_key:
            raise ValueError("DASHSCOPE_API_KEY is required when MODEL_PROVIDER=dashscope")
        if self.embedding_dim <= 0:
            raise ValueError("EMBEDDING_DIM must be positive")
        if self.max_history_messages <= 0:
            raise ValueError("MAX_HISTORY_MESSAGES must be positive")


@lru_cache
def get_settings() -> Settings:
    return Settings()

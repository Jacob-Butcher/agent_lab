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
    # 向量接口可独立配置：DeepSeek 只提供 chat，没有 /embeddings
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    # 部分厂商（如硅基流动的 BGE）不接受 dimensions 参数，置 false
    embedding_send_dimensions: bool = True

    postgres_dsn: str = "postgresql://agent:agent@db:5432/agentlab"
    redis_url: str = "redis://redis:6379/0"
    memory_backend: Literal["redis", "memory"] = "redis"
    # 向量库位置：postgres 需要 pgvector；memory 用于无 Docker 的本地演示
    store_backend: Literal["postgres", "memory"] = "postgres"
    session_ttl_seconds: int = 86400
    max_history_messages: int = 12

    rag_top_k: int = 5
    rag_score_threshold: float = 0.30
    ingest_on_startup: bool = True
    corpus_dir: str = "data/corpus"
    upload_dir: str = "data/uploads"
    admin_token: str = ""
    max_upload_bytes: int = 2 * 1024 * 1024
    demo_dir: str = "demo"

    max_message_chars: int = 2000
    log_level: str = "INFO"

    @property
    def is_mock(self) -> bool:
        return self.model_provider == "mock"

    @property
    def resolved_embedding_base_url(self) -> str:
        return self.embedding_base_url or self.dashscope_base_url

    @property
    def resolved_embedding_api_key(self) -> str:
        return self.embedding_api_key or self.dashscope_api_key

    def validate_runtime(self) -> None:
        if not self.is_mock and not self.dashscope_api_key:
            raise ValueError("DASHSCOPE_API_KEY is required when MODEL_PROVIDER=dashscope")
        if self.embedding_dim <= 0:
            raise ValueError("EMBEDDING_DIM must be positive")
        if self.embedding_base_url and not self.embedding_api_key:
            raise ValueError("EMBEDDING_API_KEY is required when EMBEDDING_BASE_URL is set")
        if self.max_history_messages <= 0:
            raise ValueError("MAX_HISTORY_MESSAGES must be positive")


@lru_cache
def get_settings() -> Settings:
    return Settings()

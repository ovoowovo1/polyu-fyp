from functools import lru_cache
from typing import List, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


EmbeddingColumn = Literal["embedding", "embedding_v2"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 3000
    cors_origins: List[str] = ["*"]

    llm_api_keys: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "google/gemini-3-flash-preview"
    google_tts_model: str = "gemini-2.5-flash-preview-tts"

    embedding_api_key: str = ""
    embedding_base_url: str = "https://openrouter.ai/api/v1"
    embedding_model: str = "google/gemini-embedding-001"
    embedding_active_column: EmbeddingColumn = "embedding"
    embedding_fallback_model: str = "google/gemini-embedding-2-preview"
    embedding_fallback_column: EmbeddingColumn = "embedding_v2"
    eval_llm_api_key: str = ""
    eval_llm_base_url: str = "https://www.chataiapi.com/v1"
    eval_llm_model: str = "gemini-2.5-flash"
    eval_embedding_api_key: str = ""
    eval_embedding_base_url: str = ""
    eval_embedding_model: str = ""

    user_agent: str = "RAG-FastAPI"

    pg_dsn: str = "postgresql://postgres:password@localhost:5432/postgres"

    jwt_secret_key: str = "123456789"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore

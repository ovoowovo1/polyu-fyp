from functools import lru_cache
from typing import List, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


EmbeddingColumn = Literal["embedding", "embedding_v2"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 3000
    cors_origins: List[str] = ["*"]

    neo4j_uri: str = "neo4j+ssc://localhost"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"

    google_api_key_list: str = ""
    genai_api_key: str = ""
    genai_base_url: str = ""
    google_ai_model: str = "google/gemini-3-flash-preview"
    google_ai_embeddings: str = "gemini-embedding-001"
    google_tts_model: str = "gemini-2.5-flash-preview-tts"

    openai_embedding_api_key: str = ""
    openai_embedding_base_url: str = "https://openrouter.ai/api/v1"
    openai_embedding_model: str = "google/gemini-embedding-001"
    openai_embedding_active_column: EmbeddingColumn = "embedding"
    openai_embedding_fallback_model: str = "google/gemini-embedding-2-preview"
    openai_embedding_fallback_column: EmbeddingColumn = "embedding_v2"
    eval_llm_api_key: str = ""
    eval_llm_base_url: str = "https://www.chataiapi.com/v1"
    eval_llm_model: str = "gemini-2.5-flash"
    eval_embedding_api_key: str = ""
    eval_embedding_base_url: str = ""
    eval_embedding_model: str = ""

    jina_api_key: str = ""

    user_agent: str = "RAG-FastAPI"

    pg_dsn: str = "postgresql://postgres:password@localhost:5432/postgres"

    jwt_secret_key: str = "123456789"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore

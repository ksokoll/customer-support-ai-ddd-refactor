# core/config.py
"""Central configuration via pydantic-settings.

All contexts import from here. No context hardcodes configuration values.
All fields have defaults so the application starts without a .env file
(useful for unit tests and local development without credentials).
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration driven by environment variables."""

    # Application metadata
    app_name: str = Field(default="Customer Support AI")
    app_version: str = Field(default="0.1.0")

    # LLM
    openai_api_key: str | None = Field(default=None)
    llm_model_name: str = Field(default="gpt-4o-mini")
    embedding_model_name: str = Field(default="text-embedding-3-small")

    # Temperature per use case
    temperature_default: float = Field(default=0.3)
    temperature_judge: float = Field(default=0.0)
    max_tokens: int = Field(default=500)

    # Input validation
    min_query_length: int = Field(default=10)
    max_query_length: int = Field(default=1000)

    # Retrieval
    retrieval_top_k: int = Field(default=3)
    vector_db_path: str = Field(default="data/vector_db")
    knowledge_base_path: str = Field(default="data/faq.jsonl")

    # Azure Blob -- optional, only required when enable_blob_retrieval=True
    enable_blob_retrieval: bool = Field(default=False)
    blob_connection_string: str | None = Field(default=None)
    blob_container_name: str | None = Field(default=None)
    knowledge_blob_name: str = Field(default="faq.jsonl")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


settings = Settings()
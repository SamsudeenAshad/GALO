"""Environment-driven configuration for GALO.

All settings are read from environment variables (or a local ``.env``) with the
``GALO_`` prefix. See ``.env.example`` for the documented surface.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GALO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Ollama ---
    ollama_base_url: str = "http://localhost:11434"
    gen_model: str = "gemma3"
    embed_model: str = "nomic-embed-text"
    # Must match the embedding model's output dimension; pins the pgvector column.
    embed_dim: int = 768
    model_timeout_s: float = 60.0

    # --- Postgres + pgvector ---
    pg_dsn: str = "postgresql://galo:galo@localhost:5432/galo"

    # --- Neo4j ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"

    # --- Retrieval ---
    retrieve_k: int = 10
    graph_hops: int = 2
    rrf_k: int = 60

    # --- Chunking ---
    chunk_size: int = 800
    chunk_overlap: int = 120

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()

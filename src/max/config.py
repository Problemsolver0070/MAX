"""Centralized configuration for Max, loaded from environment variables and .env file."""

from urllib.parse import quote_plus

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Required env vars:
        ANTHROPIC_API_KEY: Anthropic API key for Claude access.
        POSTGRES_PASSWORD: PostgreSQL password.

    All other settings have sensible defaults for local development.
    """

    # Anthropic
    anthropic_api_key: str

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "max"
    postgres_user: str = "max"
    postgres_password: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Max
    max_log_level: str = "DEBUG"
    max_owner_telegram_id: str = ""
    max_owner_whatsapp_id: str = ""

    # Voyage AI (embeddings)
    voyage_api_key: str = ""

    # Memory system
    memory_compaction_interval_seconds: int = 60
    memory_warm_budget_tokens: int = 100_000
    memory_graph_cache_max_nodes: int = 500
    memory_embedding_dimension: int = 1024
    memory_anchor_re_evaluation_interval_hours: int = 6

    @property
    def postgres_dsn(self) -> str:
        """Build a PostgreSQL connection string from individual components."""
        return (
            f"postgresql://{self.postgres_user}:{quote_plus(self.postgres_password)}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

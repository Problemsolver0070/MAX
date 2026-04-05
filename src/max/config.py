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

    # Telegram
    telegram_bot_token: str = ""

    # Communication behavior
    comm_batch_interval_seconds: int = 30
    comm_max_batch_size: int = 10
    comm_context_window_size: int = 20
    comm_media_dir: str = "/tmp/max/media"

    # Webhook (production)
    comm_webhook_enabled: bool = False
    comm_webhook_host: str = "0.0.0.0"
    comm_webhook_port: int = 8443
    comm_webhook_path: str = "/webhook/telegram"
    comm_webhook_url: str = ""
    comm_webhook_secret: str = ""

    # Command chain
    coordinator_model: str = "claude-opus-4-6"
    planner_model: str = "claude-opus-4-6"
    orchestrator_model: str = "claude-opus-4-6"
    worker_model: str = "claude-opus-4-6"
    coordinator_max_active_tasks: int = 5
    planner_max_subtasks: int = 10
    worker_max_retries: int = 2
    worker_timeout_seconds: int = 300

    # Quality Gate
    quality_director_model: str = "claude-opus-4-6"
    auditor_model: str = "claude-opus-4-6"
    quality_max_fix_attempts: int = 2
    quality_audit_timeout_seconds: int = 120
    quality_pass_threshold: float = 0.7
    quality_high_score_threshold: float = 0.9
    quality_max_rules_per_audit: int = 5
    quality_max_recent_verdicts: int = 50

    # Tool system
    tool_execution_timeout_seconds: int = 60
    tool_max_concurrent: int = 10
    tool_audit_enabled: bool = True
    tool_shell_timeout_seconds: int = 30
    tool_http_timeout_seconds: int = 30

    # Email (SMTP/IMAP)
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_imap_host: str = ""
    email_user: str = ""
    email_password: str = ""

    # Calendar (CalDAV)
    caldav_url: str = ""
    caldav_user: str = ""
    caldav_password: str = ""

    # Web search
    brave_search_api_key: str = ""

    # Browser
    browser_headless: bool = True
    browser_max_pages: int = 5

    # ── Evolution System ────────────────────────────────────────────────
    evolution_scout_interval_hours: int = 6
    evolution_canary_replay_count: int = 5
    evolution_min_priority: float = 0.3
    evolution_max_concurrent: int = 1
    evolution_freeze_consecutive_drops: int = 2
    evolution_preference_refresh_signals: int = 10
    evolution_canary_timeout_seconds: int = 300
    evolution_snapshot_retention_days: int = 30

    # ── Sentinel Anti-Degradation ───────────────────────────────────────
    sentinel_model: str = "claude-opus-4-6"
    sentinel_replay_count: int = 10
    sentinel_monitor_interval_hours: int = 12
    sentinel_timeout_seconds: int = 600
    sentinel_judge_temperature: float = 0.0

    # ── Go-Live Infrastructure ─────────────────────────────────────────
    # API Server
    max_host: str = "0.0.0.0"
    max_port: int = 8080
    max_api_keys: str = ""  # comma-separated valid API keys

    # Rate Limiting
    rate_limit_api: str = "60/minute"
    rate_limit_messaging: str = "30/minute"

    # Circuit Breaker
    llm_circuit_breaker_threshold: int = 5
    llm_circuit_breaker_cooldown_seconds: int = 60

    # Bus Transport
    bus_transport: str = "streams"  # "streams" or "pubsub"
    bus_dead_letter_max_retries: int = 3
    bus_stream_max_len: int = 10000
    bus_consumer_group: str = "max_workers"
    bus_consumer_name: str = "worker-1"

    # Task Recovery
    task_recovery_enabled: bool = True
    task_timeout_watchdog_interval_seconds: int = 60

    # Observability
    otel_enabled: bool = False
    otel_service_name: str = "max"
    otel_exporter_endpoint: str = ""

    # Azure
    azure_key_vault_url: str = ""

    @property
    def postgres_dsn(self) -> str:
        """Build a PostgreSQL connection string from individual components."""
        return (
            f"postgresql://{self.postgres_user}:{quote_plus(self.postgres_password)}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

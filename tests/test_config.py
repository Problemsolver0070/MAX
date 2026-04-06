from max.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_HOST", "db.example.com")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "max_test")
    monkeypatch.setenv("POSTGRES_USER", "testuser")
    monkeypatch.setenv("POSTGRES_PASSWORD", "testpass")
    monkeypatch.setenv("REDIS_URL", "redis://redis.example.com:6380/1")
    monkeypatch.setenv("MAX_LOG_LEVEL", "WARNING")

    settings = Settings()
    assert settings.anthropic_api_key == "sk-ant-test-key"
    assert settings.postgres_host == "db.example.com"
    assert settings.postgres_port == 5433
    assert settings.postgres_db == "max_test"
    assert settings.redis_url == "redis://redis.example.com:6380/1"
    assert settings.max_log_level == "WARNING"


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_PASSWORD", "testpass")
    settings = Settings()
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432
    assert settings.postgres_db == "max"
    assert settings.max_log_level == "DEBUG"


def test_postgres_dsn(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_USER", "max")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "max")
    settings = Settings()
    assert settings.postgres_dsn == "postgresql://max:secret@localhost:5432/max"


def test_postgres_dsn_special_chars(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_USER", "max")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss/w#rd")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "max")
    settings = Settings()
    assert settings.postgres_dsn == "postgresql://max:p%40ss%2Fw%23rd@localhost:5432/max"


def test_memory_settings_defaults(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    settings = Settings()
    assert settings.memory_compaction_interval_seconds == 60
    assert settings.memory_warm_budget_tokens == 100_000
    assert settings.memory_graph_cache_max_nodes == 500
    assert settings.memory_embedding_dimension == 1024
    assert settings.memory_anchor_re_evaluation_interval_hours == 6


def test_voyage_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-test-voyage-key")
    from max.config import Settings

    s = Settings()
    assert s.voyage_api_key == "pa-test-voyage-key"


def test_comm_settings_defaults(settings):
    assert settings.telegram_bot_token == ""
    assert settings.comm_batch_interval_seconds == 30
    assert settings.comm_max_batch_size == 10
    assert settings.comm_context_window_size == 20
    assert settings.comm_media_dir == "/tmp/max/media"
    assert settings.comm_webhook_enabled is False
    assert settings.comm_webhook_host == "0.0.0.0"
    assert settings.comm_webhook_port == 8443
    assert settings.comm_webhook_path == "/webhook/telegram"
    assert settings.comm_webhook_url == ""
    assert settings.comm_webhook_secret == ""


def test_command_chain_settings_defaults(settings):
    assert settings.coordinator_model == "claude-opus-4-6"
    assert settings.planner_model == "claude-opus-4-6"
    assert settings.orchestrator_model == "claude-opus-4-6"
    assert settings.worker_model == "claude-opus-4-6"
    assert settings.coordinator_max_active_tasks == 5
    assert settings.planner_max_subtasks == 10
    assert settings.worker_max_retries == 2
    assert settings.worker_timeout_seconds == 300


def test_quality_gate_settings_defaults(settings):
    assert settings.quality_director_model == "claude-opus-4-6"
    assert settings.auditor_model == "claude-opus-4-6"
    assert settings.quality_max_fix_attempts == 2
    assert settings.quality_audit_timeout_seconds == 120
    assert settings.quality_pass_threshold == 0.7
    assert settings.quality_high_score_threshold == 0.9
    assert settings.quality_max_rules_per_audit == 5
    assert settings.quality_max_recent_verdicts == 50


def test_tool_system_settings_defaults(settings):
    assert settings.tool_execution_timeout_seconds == 60
    assert settings.tool_max_concurrent == 10
    assert settings.tool_audit_enabled is True
    assert settings.tool_shell_timeout_seconds == 30
    assert settings.tool_http_timeout_seconds == 30


def test_anthropic_base_url_default(settings):
    assert settings.anthropic_base_url == ""


def test_anthropic_base_url_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com/anthropic")
    settings = Settings()
    assert settings.anthropic_base_url == "https://example.com/anthropic"

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

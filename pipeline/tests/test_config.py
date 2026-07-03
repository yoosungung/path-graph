import os

from path_graph.config import Settings, get_settings


def test_postgres_dsn_fallback(monkeypatch):
    monkeypatch.delenv("PATH_GRAPH_DSN", raising=False)
    monkeypatch.setenv(
        "POSTGRES_DSN",
        "postgresql+asyncpg://runtime:runtime@127.0.0.1:5432/runtime?sslmode=disable",
    )
    get_settings.cache_clear()
    s = Settings()
    assert s.path_graph_dsn.startswith("postgresql://runtime:")
    get_settings.cache_clear()


def test_nebula_url_parsed(monkeypatch):
    monkeypatch.setenv("NEBULA_URL", "graph.example.com:9669")
    get_settings.cache_clear()
    s = Settings()
    assert s.nebula_host == "graph.example.com"
    assert s.nebula_port == 9669
    get_settings.cache_clear()


def test_env_file_fields(monkeypatch):
    monkeypatch.setenv("PATH_GRAPH_TENANT", "acme")
    get_settings.cache_clear()
    s = Settings()
    assert s.path_graph_tenant == "acme"
    get_settings.cache_clear()

import pytest

from constants import PROJECT_ID


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    root = tmp_path / "blob"
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch):
    """Unit tests must not require live PG/envoy from .env.dev.local."""
    monkeypatch.setenv("PATH_GRAPH_DSN", "")
    monkeypatch.setenv("PIPELINE_AGENT_ACCESS_TOKEN", "")
    from path_graph.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

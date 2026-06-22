import pytest


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    root = tmp_path / "blob"
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from path_graph.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

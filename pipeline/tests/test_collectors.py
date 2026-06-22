import pytest

from path_graph.collectors.gdrive_auth import GDriveAuthError
from path_graph.collectors.ms_graph_auth import GraphAuthError
from path_graph.collectors.remote import AgentChatCollector, GDriveCollector, OneDriveCollector


def test_gdrive_requires_token():
    with pytest.raises(GDriveAuthError):
        GDriveCollector().collect_file("fid", "dev", "gdrive")


def test_onedrive_requires_token():
    with pytest.raises(GraphAuthError):
        OneDriveCollector().collect_file("iid", "dev", "onedrive")


def test_agent_chat_collect(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(tmp_path / "blob"))
    from path_graph.config import get_settings

    get_settings.cache_clear()
    p = tmp_path / "chat.json"
    p.write_text('{"messages":[]}', encoding="utf-8")
    meta = AgentChatCollector().collect_json(p, "dev", "chat")
    assert meta["tenant"] == "dev"
    assert meta["filename"] == "conversation.json"
    get_settings.cache_clear()

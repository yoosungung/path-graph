from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from path_graph.collectors.gdrive_auth import GDriveAuthError, RefreshTokenProvider, make_gdrive_token_provider
from path_graph.collectors.ms_graph_auth import GraphAuthError, make_onedrive_token_provider
from path_graph.collectors.remote import GDriveCollector, OneDriveCollector
from path_graph.collectors.gdrive import GDriveClient
from path_graph.collectors.onedrive import OneDriveClient
from path_graph.config import Settings
from constants import PROJECT_ID


@pytest.fixture
def local_store(monkeypatch, tmp_path):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(tmp_path / "blob"))
    monkeypatch.setenv("PATH_GRAPH_DSN", "")
    from path_graph.config import get_settings

    get_settings.cache_clear()
    yield tmp_path / "blob"
    get_settings.cache_clear()


def test_gdrive_requires_refresh_token():
    with pytest.raises(GDriveAuthError, match="GDRIVE_REFRESH_TOKEN"):
        make_gdrive_token_provider(
            Settings(gdrive_client_id="c", gdrive_client_secret="s")
        )


def test_gdrive_auth_token():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "gdrive-token", "expires_in": 3600})
        return httpx.Response(404)

    provider = RefreshTokenProvider("c", "s", "refresh")
    provider._http = httpx.Client(transport=httpx.MockTransport(handler))
    assert provider.get_token() == "gdrive-token"


def _gdrive_transport(folder_id: str = "folder-1") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "files?q=" in url and "folder-1" in url:
            return httpx.Response(
                200,
                json={
                    "files": [
                        {"id": "f1", "name": "note.txt", "mimeType": "text/plain"},
                        {"id": "sub", "name": "sub", "mimeType": "application/vnd.google-apps.folder"},
                    ]
                },
            )
        if "files?q=" in url and "sub" in url:
            return httpx.Response(
                200,
                json={"files": [{"id": "f2", "name": "deep.pdf", "mimeType": "application/pdf"}]},
            )
        if url.endswith("/files/f1?alt=media"):
            return httpx.Response(200, content=b"gdrive text")
        if url.endswith("/files/f2?alt=media"):
            return httpx.Response(200, content=b"%PDF")
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_gdrive_collect_folder(local_store):
    provider = MagicMock()
    provider.get_token.return_value = "token"
    client = GDriveClient(provider, http_client=httpx.Client(transport=_gdrive_transport()))
    collector = GDriveCollector(client=client)
    items = collector.collect_folder(
        "dev", PROJECT_ID, "gdrive", folder_id="folder-1", extensions={".txt", ".pdf"}
    )
    assert len(items) == 2
    assert {i["filename"] for i in items} == {"note.txt", "deep.pdf"}


def test_onedrive_requires_token():
    with pytest.raises(GraphAuthError, match="ONEDRIVE_REFRESH_TOKEN"):
        make_onedrive_token_provider(Settings(ms_tenant_id="t", ms_client_id="c"))


def _onedrive_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/me/drive/root:/Docs:/children"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"id": "i1", "name": "a.txt", "file": {"mimeType": "text/plain"}},
                        {"id": "d1", "name": "sub", "folder": {}},
                    ]
                },
            )
        if path.endswith("/me/drive/root:/Docs/sub:/children"):
            return httpx.Response(
                200,
                json={"value": [{"id": "i2", "name": "b.pdf", "file": {}}]},
            )
        if path.endswith("/items/i1/content"):
            return httpx.Response(200, content=b"onedrive")
        if path.endswith("/items/i2/content"):
            return httpx.Response(200, content=b"%PDF")
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_onedrive_collect_folder(local_store):
    provider = MagicMock()
    provider.get_token.return_value = "token"
    client = OneDriveClient(provider, http_client=httpx.Client(transport=_onedrive_transport()))
    collector = OneDriveCollector(client=client)
    items = collector.collect_folder("dev", PROJECT_ID, "onedrive", folder="Docs")
    assert len(items) == 2
    assert {i["filename"] for i in items} == {"a.txt", "b.pdf"}


def test_ingest_gdrive_cli(local_store, monkeypatch):
    provider = MagicMock()
    provider.get_token.return_value = "token"
    client = GDriveClient(provider, http_client=httpx.Client(transport=_gdrive_transport()))
    monkeypatch.setattr(
        "path_graph.steps.ingest_gdrive.GDriveCollector",
        lambda: GDriveCollector(client=client),
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest_gdrive.resolve_project_slug",
        lambda *a, **k: "default",
    )
    from path_graph.steps import ingest_gdrive

    assert ingest_gdrive.main(
        ["--tenant", "dev", "--project-id", PROJECT_ID, "--folder-id", "folder-1", "--batch-id", "g1"]
    ) == 0


def test_ingest_onedrive_dry_run(capsys, monkeypatch):
    provider = MagicMock()
    provider.get_token.return_value = "token"
    client = OneDriveClient(provider, http_client=httpx.Client(transport=_onedrive_transport()))
    monkeypatch.setattr(
        "path_graph.steps.ingest_onedrive.OneDriveCollector",
        lambda: OneDriveCollector(client=client),
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest_onedrive.resolve_project_slug",
        lambda *a, **k: "default",
    )
    from path_graph.steps import ingest_onedrive

    rc = ingest_onedrive.main(
        ["--tenant", "dev", "--project-id", PROJECT_ID, "--folder", "Docs", "--dry-run"]
    )
    assert rc == 0
    assert "a.txt" in capsys.readouterr().out

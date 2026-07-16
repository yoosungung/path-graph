from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from path_graph.collectors.ms_graph_auth import (
    AppTokenProvider,
    DelegatedTokenProvider,
    GraphAuthError,
    make_token_provider,
)
from path_graph.collectors.remote import SharePointCollector
from path_graph.collectors.sharepoint import SharePointClient, SharePointError
from path_graph.config import Settings
from path_graph.contracts.s3_keys import s3_key_batch_manifest
from path_graph.storage.blob import read_jsonl
from constants import PROJECT_ID


def _minimal_pdf_bytes() -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Collector fixture PDF body text.")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def local_store(monkeypatch, tmp_path):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(tmp_path / "blob"))
    from path_graph.config import get_settings

    get_settings.cache_clear()
    yield tmp_path / "blob"
    get_settings.cache_clear()


def test_s3_key_batch_manifest():
    assert s3_key_batch_manifest("dev", "20250622") == "batches/dev/20250622/manifest.jsonl"


def test_app_auth_token():
    mock_app = MagicMock()
    mock_app.acquire_token_for_client.return_value = {
        "access_token": "app-token",
        "expires_in": 3600,
    }
    with patch(
        "path_graph.collectors.ms_graph_auth.msal.ConfidentialClientApplication",
        return_value=mock_app,
    ):
        provider = AppTokenProvider("tenant", "client", "secret")
        assert provider.get_token() == "app-token"
        assert provider.get_token() == "app-token"
        mock_app.acquire_token_for_client.assert_called_once()


def test_delegated_requires_refresh_token():
    with pytest.raises(GraphAuthError, match="MS_REFRESH_TOKEN"):
        make_token_provider(
            Settings(
                ms_auth_mode="delegated",
                ms_tenant_id="t",
                ms_client_id="c",
            )
        )


def test_delegated_auth_token():
    mock_app = MagicMock()
    mock_app.acquire_token_by_refresh_token.return_value = {
        "access_token": "delegated-token",
        "expires_in": 3600,
    }
    with patch(
        "path_graph.collectors.ms_graph_auth.msal.PublicClientApplication",
        return_value=mock_app,
    ):
        provider = DelegatedTokenProvider("tenant", "client", "refresh-xyz")
        assert provider.get_token() == "delegated-token"


def _graph_transport(site_id: str = "site-1", drive_id: str = "drive-1") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/sites/tripodoffice.sharepoint.com:/sites/kms"):
            return httpx.Response(200, json={"id": site_id, "name": "kms"})
        if f"/sites/{site_id}/drives" in path:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": drive_id,
                            "name": "Documents",
                            "webUrl": "https://tripodoffice.sharepoint.com/sites/kms/Shared%20Documents",
                        }
                    ]
                },
            )
        if "/root:/회사규정:/children" in path:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "item-1",
                            "name": "규정.txt",
                            "file": {"mimeType": "text/plain"},
                        },
                        {"id": "folder-1", "name": "sub", "folder": {}},
                    ]
                },
            )
        if "/root:/회사규정/sub:/children" in path:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "item-2",
                            "name": "nested.pdf",
                            "file": {"mimeType": "application/pdf"},
                        }
                    ]
                },
            )
        if path.endswith("/items/item-1/content"):
            return httpx.Response(200, content=b"hello sharepoint")
        if path.endswith("/items/item-2/content"):
            return httpx.Response(200, content=_minimal_pdf_bytes())
        return httpx.Response(404, json={"error": {"message": "not found"}})

    return httpx.MockTransport(handler)


def test_resolve_site_and_drive():
    provider = MagicMock()
    provider.get_token.return_value = "token"
    client = SharePointClient(
        provider,
        http_client=httpx.Client(transport=_graph_transport()),
    )
    site = client.resolve_site("tripodoffice.sharepoint.com:/sites/kms")
    assert site["id"] == "site-1"
    drive = client.resolve_drive("site-1", "Documents")
    assert drive["id"] == "drive-1"


def test_list_folder_pagination():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/children"):
            if "page=2" in str(request.url):
                return httpx.Response(
                    200,
                    json={"value": [{"id": "b", "name": "b.txt", "file": {}}]},
                )
            return httpx.Response(
                200,
                json={
                    "value": [{"id": "a", "name": "a.txt", "file": {}}],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/drives/d1/root:/f:/children?page=2",
                },
            )
        return httpx.Response(404)

    provider = MagicMock()
    provider.get_token.return_value = "token"
    client = SharePointClient(provider, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    items = client.list_folder_items("d1", "f")
    assert [i["name"] for i in items] == ["a.txt", "b.txt"]
    assert len(calls) == 2


def test_collect_folder_stores_raw(local_store):
    provider = MagicMock()
    provider.get_token.return_value = "token"
    client = SharePointClient(
        provider,
        http_client=httpx.Client(transport=_graph_transport()),
    )
    collector = SharePointCollector(client=client)
    items = collector.collect_folder(
        "dev",
        PROJECT_ID,
        "sharepoint:kms",
        site="tripodoffice.sharepoint.com:/sites/kms",
        drive_name="Documents",
        folder="회사규정",
        extensions={".txt", ".pdf"},
    )
    assert len(items) == 2
    names = {i["filename"] for i in items}
    assert names == {"규정.txt", "nested.pdf"}
    # idempotent second run
    again = collector.collect_folder(
        "dev",
        PROJECT_ID,
        "sharepoint:kms",
        site="tripodoffice.sharepoint.com:/sites/kms",
        drive_name="Documents",
        folder="회사규정",
        extensions={".txt", ".pdf"},
    )
    assert len(again) == 2


def test_write_batch_manifest(local_store):
    provider = MagicMock()
    provider.get_token.return_value = "token"
    client = SharePointClient(
        provider,
        http_client=httpx.Client(transport=_graph_transport()),
    )
    collector = SharePointCollector(client=client)
    items = collector.collect_folder("dev", PROJECT_ID, "sharepoint:kms", folder="회사규정")
    uri = collector.write_batch_manifest("dev", "batch-1", items)
    assert "batches/dev/batch-1/manifest.jsonl" in uri
    from path_graph.config import get_settings
    from path_graph.storage.blob import make_blob_store

    rows = read_jsonl(make_blob_store(get_settings()), s3_key_batch_manifest("dev", "batch-1"))
    assert len(rows) == 2
    assert rows[0]["tenant"] == "dev"
    assert rows[0]["source_id"] == "sharepoint:kms"
    assert "content_hash" in rows[0]


def test_sharepoint_error_on_403():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "Access denied"}})

    provider = MagicMock()
    provider.get_token.return_value = "token"
    client = SharePointClient(provider, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(SharePointError, match="403"):
        client.resolve_site("host:/sites/kms")


def test_ingest_sharepoint_cli(local_store, monkeypatch):
    monkeypatch.setenv("PATH_GRAPH_DSN", "")
    from path_graph.config import get_settings

    get_settings.cache_clear()
    provider = MagicMock()
    provider.get_token.return_value = "token"
    client = SharePointClient(
        provider,
        http_client=httpx.Client(transport=_graph_transport()),
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest_sharepoint.SharePointCollector",
        lambda: SharePointCollector(client=client),
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest_sharepoint.resolve_project_slug",
        lambda *a, **k: "default",
    )
    from path_graph.steps import ingest_sharepoint

    rc = ingest_sharepoint.main(
        [
            "--tenant",
            "dev",
            "--project-id",
            PROJECT_ID,
            "--source-id",
            "sharepoint:kms",
            "--folder",
            "회사규정",
            "--batch-id",
            "t1",
        ]
    )
    assert rc == 0
    get_settings.cache_clear()


def test_ingest_sharepoint_rag_flag(local_store, monkeypatch):
    monkeypatch.setenv("PATH_GRAPH_DSN", "")
    from path_graph.config import get_settings

    get_settings.cache_clear()
    provider = MagicMock()
    provider.get_token.return_value = "token"
    client = SharePointClient(
        provider,
        http_client=httpx.Client(transport=_graph_transport()),
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest_sharepoint.SharePointCollector",
        lambda: SharePointCollector(client=client),
    )
    rag_calls: list[str] = []

    monkeypatch.setattr(
        "path_graph.steps.ingest_sharepoint.resolve_project_slug",
        lambda *a, **k: "default",
    )
    def fake_rag(tenant, chunks_key, document_id, project_slug, **kwargs):
        rag_calls.append(document_id)
        return 1

    monkeypatch.setattr("path_graph.steps.ingest_helpers.index_rag_for_document", fake_rag)
    from path_graph.steps import ingest_sharepoint

    rc = ingest_sharepoint.main(
        [
            "--tenant",
            "dev",
            "--project-id",
            PROJECT_ID,
            "--folder",
            "회사규정",
            "--batch-id",
            "t2",
            "--rag",
        ]
    )
    assert rc == 0
    assert len(rag_calls) == 2
    get_settings.cache_clear()


def test_ingest_sharepoint_dry_run(capsys, monkeypatch):
    monkeypatch.setenv("PATH_GRAPH_DSN", "")
    from path_graph.config import get_settings

    get_settings.cache_clear()
    provider = MagicMock()
    provider.get_token.return_value = "token"
    client = SharePointClient(
        provider,
        http_client=httpx.Client(transport=_graph_transport()),
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest_sharepoint.SharePointCollector",
        lambda: SharePointCollector(client=client),
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest_sharepoint.resolve_project_slug",
        lambda *a, **k: "default",
    )
    from path_graph.steps import ingest_sharepoint

    rc = ingest_sharepoint.main(
        ["--tenant", "dev", "--project-id", PROJECT_ID, "--folder", "회사규정", "--dry-run"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "규정.txt" in out
    get_settings.cache_clear()

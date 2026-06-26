from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from path_graph.admin.runner import collect_source, probe_source, read_manifest_lines
from path_graph.contracts.source import SourceDriver, SourceProfile
from path_graph.storage.blob import LocalBlobStore, write_jsonl


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("PATH_GRAPH_DSN", raising=False)
    from path_graph.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


from constants import PROJECT_ID


def _profile() -> SourceProfile:
    return SourceProfile(
        tenant="dev",
        id="11111111-1111-4111-8111-111111111111",
        project_id=PROJECT_ID,
        name="kms",
        driver=SourceDriver.SHAREPOINT,
        source_id="sharepoint:kms",
        config={"folder": "회사규정", "site": "host:/sites/kms", "drive": "Documents"},
    )


def test_test_source_sharepoint(monkeypatch):
    mock_collector = MagicMock()
    mock_collector.enumerate_files.return_value = [{"name": "a.pdf"}, {"name": "b.pdf"}]
    monkeypatch.setattr(
        "path_graph.admin.runner._sharepoint_collector",
        lambda settings=None: mock_collector,
    )
    result = probe_source(_profile())
    assert result["file_count"] == 2
    assert result["sample_names"] == ["a.pdf", "b.pdf"]


def test_collect_and_read_manifest(local_store, monkeypatch):
    mock_collector = MagicMock()
    mock_collector.collect_folder.return_value = [
        {
            "tenant": "dev",
            "project_id": PROJECT_ID,
            "source_id": "sharepoint:kms",
            "content_hash": "abc",
            "document_id": "doc-1",
            "s3_raw_uri": "file://x",
            "filename": "a.pdf",
        }
    ]
    monkeypatch.setattr(
        "path_graph.admin.runner._sharepoint_collector",
        lambda settings=None: mock_collector,
    )
    out = collect_source(_profile(), batch_id="batch-test")
    assert out["file_count"] == 1
    assert out["manifest_key"] == "batches/dev/batch-test/manifest.jsonl"
    lines = read_manifest_lines(out["manifest_key"])
    assert len(lines) == 1
    assert lines[0]["filename"] == "a.pdf"
    assert lines[0]["project_id"] == PROJECT_ID


def test_read_manifest_lines_includes_project_id(local_store):
    from path_graph.collectors.remote import collect_local_file, write_batch_manifest
    from path_graph.config import get_settings
    from path_graph.contracts.s3_keys import s3_key_batch_manifest

    local_store.mkdir(parents=True, exist_ok=True)
    f = local_store / "doc.txt"
    f.write_text("hello", encoding="utf-8")
    meta = collect_local_file(f, "dev", PROJECT_ID, "manual:upload")
    write_batch_manifest("dev", "batch-read", [meta], get_settings())
    lines = read_manifest_lines(s3_key_batch_manifest("dev", "batch-read"))
    assert lines[0]["project_id"] == PROJECT_ID

from __future__ import annotations

from unittest.mock import MagicMock, patch

from path_graph.admin.downstream import apply_graphrag_success
from path_graph.storage.blob import LocalBlobStore, write_jsonl

from constants import PROJECT_ID


def test_apply_graphrag_success_marks_manifest_documents(local_store, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(local_store))
    monkeypatch.setenv("PATH_GRAPH_DSN", "postgresql://localhost/test")
    from path_graph.config import get_settings

    get_settings.cache_clear()

    store = LocalBlobStore(local_store)
    batch_id = "batch-graph-1"
    doc_id = "00000000-0000-0000-0000-0000000000aa"
    write_jsonl(
        f"batches/dev/{batch_id}/manifest.jsonl",
        [{"document_id": doc_id, "project_id": PROJECT_ID, "content_hash": "abc"}],
        store,
    )

    pg = MagicMock()
    pg.mark_graphrag_indexed.return_value = 1

    with patch("path_graph.admin.downstream._require_pg", return_value=pg):
        updated = apply_graphrag_success("dev", PROJECT_ID, batch_id)

    assert updated == 1
    pg.mark_graphrag_indexed.assert_called_once_with("dev", [doc_id])


def test_apply_graphrag_success_returns_zero_when_manifest_missing(local_store, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(local_store))
    monkeypatch.setenv("PATH_GRAPH_DSN", "postgresql://localhost/test")
    from path_graph.config import get_settings

    get_settings.cache_clear()

    pg = MagicMock()
    with patch("path_graph.admin.downstream._require_pg", return_value=pg):
        updated = apply_graphrag_success("dev", PROJECT_ID, "missing-batch")

    assert updated == 0
    pg.mark_graphrag_indexed.assert_not_called()

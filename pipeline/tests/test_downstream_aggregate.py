from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from path_graph.admin.downstream import (
    DownstreamBusyError,
    DownstreamValidationError,
    aggregate_batch_chunks,
    assert_project_graphrag_idle,
    prepare_graphrag_submission,
)
from path_graph.collectors.remote import write_batch_manifest
from path_graph.config import get_settings
from path_graph.contracts.s3_keys import s3_key_batch_manifest, s3_key_chunks, s3_key_chunks_project_batch
from path_graph.storage.blob import make_blob_store, read_jsonl, write_jsonl

from constants import PROJECT_ID


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("PATH_GRAPH_DSN", "postgresql://localhost/test")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _manifest_item(doc_id: str, *, project_id: str = PROJECT_ID) -> dict:
    return {
        "tenant": "dev",
        "project_id": project_id,
        "source_id": "manual:docs",
        "content_hash": f"hash-{doc_id[:8]}",
        "document_id": doc_id,
        "s3_raw_uri": f"s3://raw/{doc_id}",
        "filename": f"{doc_id}.pdf",
    }


def test_aggregate_batch_chunks_merges_multiple_docs(local_store):
    batch_id = "20260101-120000"
    doc_a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    doc_b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    write_batch_manifest(
        "dev",
        batch_id,
        [_manifest_item(doc_a), _manifest_item(doc_b)],
        get_settings(),
    )
    store = make_blob_store(get_settings())
    write_jsonl(
        s3_key_chunks("dev", doc_a),
        [{"chunk_id": "c1", "text": "alpha [[Link]]"}],
        store,
    )
    write_jsonl(
        s3_key_chunks("dev", doc_b),
        [{"chunk_id": "c2", "text": "beta"}],
        store,
    )

    mock_pg = MagicMock()
    mock_pg.get_document.side_effect = lambda _t, doc_id: {
        "document_id": doc_id,
        "ingest_state": "indexed_rag",
    }

    with patch("path_graph.admin.downstream.PgMetaStore", return_value=mock_pg):
        result = aggregate_batch_chunks("dev", PROJECT_ID, batch_id)

    expected_key = s3_key_chunks_project_batch("dev", PROJECT_ID, batch_id)
    assert result.chunks_key == expected_key
    assert result.document_count == 2
    assert result.chunk_line_count == 2
    lines = read_jsonl(store, expected_key)
    assert len(lines) == 2
    assert {line["chunk_id"] for line in lines} == {"c1", "c2"}


def test_aggregate_rejects_project_mismatch(local_store):
    batch_id = "batch-mismatch"
    doc_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    write_batch_manifest(
        "dev",
        batch_id,
        [_manifest_item(doc_id, project_id="00000000-0000-4000-8000-000000000099")],
        get_settings(),
    )
    with pytest.raises(DownstreamValidationError, match="project_id"):
        aggregate_batch_chunks("dev", PROJECT_ID, batch_id)


def test_aggregate_requires_indexed_rag(local_store):
    batch_id = "batch-pending"
    doc_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    write_batch_manifest("dev", batch_id, [_manifest_item(doc_id)], get_settings())
    mock_pg = MagicMock()
    mock_pg.get_document.return_value = {"document_id": doc_id, "ingest_state": "pending"}

    with patch("path_graph.admin.downstream.PgMetaStore", return_value=mock_pg):
        with pytest.raises(DownstreamValidationError, match="indexed_rag"):
            aggregate_batch_chunks("dev", PROJECT_ID, batch_id)


def test_aggregate_missing_manifest(local_store):
    with pytest.raises(DownstreamValidationError, match="manifest"):
        aggregate_batch_chunks("dev", PROJECT_ID, "missing-batch")


@patch("path_graph.admin.downstream.ProjectStore")
def test_prepare_graphrag_submission(mock_project_store, local_store):
    batch_id = "20260101-130000"
    doc_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    write_batch_manifest("dev", batch_id, [_manifest_item(doc_id)], get_settings())
    store = make_blob_store(get_settings())
    write_jsonl(s3_key_chunks("dev", doc_id), [{"chunk_id": "c1", "text": "x"}], store)

    mock_project_store.return_value.get_project.return_value = MagicMock(
        slug="product-docs",
    )
    mock_pg = MagicMock()
    mock_pg.get_document.return_value = {"ingest_state": "indexed_rag"}

    with patch("path_graph.admin.downstream.PgMetaStore", return_value=mock_pg):
        plan = prepare_graphrag_submission("dev", PROJECT_ID, batch_id, dsn="postgresql://x")

    assert plan.project_slug == "product-docs"
    assert plan.batch_id == batch_id
    params = {p["name"]: p["value"] for p in plan.argo_parameters()}
    assert params["project_id"] == PROJECT_ID
    assert params["tenant"] == "dev"
    assert params["chunks_key"].endswith("/chunks.jsonl")


def test_assert_project_graphrag_idle_raises_when_active():
    store = MagicMock()
    store.has_active_graphrag_run.return_value = True
    with pytest.raises(DownstreamBusyError):
        assert_project_graphrag_idle(store, "dev", PROJECT_ID, "batch-1")

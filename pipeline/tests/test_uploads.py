from __future__ import annotations

import pytest

from path_graph.admin.uploads import (
    UploadValidationError,
    build_ingest_manifest,
    filename_from_raw_uri,
    upload_raw_file,
    upload_raw_files,
)
from path_graph.contracts.source import SourceDriver, SourceProfile
from path_graph.storage.blob import read_jsonl


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("PATH_GRAPH_DSN", raising=False)
    from path_graph.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _manual_profile(**overrides) -> SourceProfile:
    base = dict(
        tenant="dev",
        id="11111111-1111-4111-8111-111111111111",
        name="manual-docs",
        driver=SourceDriver.MANUAL,
        source_id="manual:docs",
        config={},
    )
    base.update(overrides)
    return SourceProfile(**base)


def test_filename_from_raw_uri():
    assert filename_from_raw_uri("s3://path-graph/raw/dev/manual/a/b.pdf") == "b.pdf"
    assert filename_from_raw_uri("file:///data/raw/dev/x/hash/doc.pdf") == "doc.pdf"


def test_upload_raw_file_stores_bytes(local_store):
    profile = _manual_profile()
    result = upload_raw_file(profile, b"hello", "a.txt")
    assert result["status"] == "uploaded"
    assert result["skipped"] is False
    assert len(result["content_hash"]) == 64


def test_upload_raw_file_idempotent_skip(local_store):
    profile = _manual_profile()
    first = upload_raw_file(profile, b"same", "a.pdf")
    second = upload_raw_file(profile, b"same", "a.pdf")
    assert first["status"] == "uploaded"
    assert second["status"] == "skipped"
    assert second["reason"] == "already_exists"


def test_upload_rejects_non_manual_driver(local_store):
    profile = _manual_profile(driver=SourceDriver.SHAREPOINT)
    with pytest.raises(UploadValidationError, match="manual"):
        upload_raw_file(profile, b"x", "a.pdf")


def test_upload_rejects_extension(local_store):
    profile = _manual_profile(config={"allowed_extensions": ".pdf"})
    with pytest.raises(UploadValidationError, match="extension"):
        upload_raw_file(profile, b"x", "notes.txt")


def test_manual_default_extensions_allow_office_formats(local_store):
    profile = _manual_profile(config={})
    for name in ("a.hwpx", "b.doc", "c.xls", "d.xlsx"):
        result = upload_raw_file(profile, b"x", name)
        assert result["status"] == "uploaded"


def test_legacy_manual_extensions_expanded(local_store):
    profile = _manual_profile(
        config={"allowed_extensions": ".pdf,.hwp,.docx,.txt,.md"},
    )
    result = upload_raw_file(profile, b"x", "sheet.xlsx")
    assert result["status"] == "uploaded"


def test_upload_rejects_size(local_store):
    profile = _manual_profile(config={"max_file_mb": 0})
    with pytest.raises(UploadValidationError, match="size"):
        upload_raw_file(profile, b"1234", "a.pdf", server_max_mb=0)


def test_upload_raw_files_batch(local_store):
    profile = _manual_profile()
    out = upload_raw_files(
        profile,
        [
            ("a.pdf", b"one", "application/pdf"),
            ("b.pdf", b"two", "application/pdf"),
        ],
    )
    assert out["uploaded_count"] == 2
    assert len(out["items"]) == 2


def test_build_ingest_manifest_pending_only(local_store, monkeypatch):
    profile = _manual_profile()
    upload_raw_file(profile, b"doc-one", "one.pdf")
    upload_raw_file(profile, b"doc-two", "two.pdf")

    docs = [
        {
            "document_id": "11111111-1111-4111-8111-111111111111",
            "source_id": profile.source_id,
            "content_hash": "abc",
            "ingest_state": "pending",
            "s3_raw_uri": "file://x/one.pdf",
            "filename": "one.pdf",
        },
        {
            "document_id": "22222222-2222-4222-8222-222222222222",
            "source_id": profile.source_id,
            "content_hash": "def",
            "ingest_state": "indexed_rag",
            "s3_raw_uri": "file://x/two.pdf",
            "filename": "two.pdf",
        },
    ]
    monkeypatch.setattr(
        "path_graph.admin.uploads.list_documents_for_source",
        lambda tenant, profile, **kwargs: [
            d
            for d in docs
            if kwargs.get("ingest_state") is None or d["ingest_state"] == kwargs["ingest_state"]
        ],
    )

    out = build_ingest_manifest(profile, document_ids=None, batch_id="batch-test")
    assert out["batch_id"] == "batch-test"
    assert out["file_count"] == 1
    assert "batches/dev/batch-test/manifest.jsonl" == out["manifest_key"]

    from path_graph.config import get_settings
    from path_graph.storage.blob import make_blob_store

    lines = read_jsonl(make_blob_store(get_settings()), out["manifest_key"])
    assert len(lines) == 1
    assert lines[0]["filename"] == "one.pdf"

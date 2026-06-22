import json
from pathlib import Path

import pytest

from path_graph.collectors.remote import collect_local_file
from path_graph.config import Settings
from path_graph.steps.ingest import ingest_raw_bytes
from path_graph.storage.blob import LocalBlobStore


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(tmp_path))
    return tmp_path


def test_collect_and_ingest_txt(local_store, monkeypatch):
    monkeypatch.setattr(
        "path_graph.parsers.parse.parse_document",
        lambda data, filename, rhwp_bin="rhwp-batch": ("# Title\n\nBody text", None),
    )
    f = local_store / "sample.txt"
    f.write_text("hello", encoding="utf-8")
    meta = collect_local_file(f, "dev", "local")
    data = f.read_bytes()
    result = ingest_raw_bytes(data, "sample.txt", "dev", "local", meta)
    assert "chunks_key" in result
    assert result["chunks"]


def test_ingest_parse_failure_dead_letter(local_store, monkeypatch):
    monkeypatch.setattr(
        "path_graph.steps.ingest.parse_document",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    meta = {
        "tenant": "dev",
        "document_id": "00000000-0000-0000-0000-000000000001",
        "content_hash": "abc",
        "source_id": "x",
        "s3_raw_uri": "file://x",
        "filename": "bad.bin",
    }
    from path_graph.steps.ingest import ParseError

    with pytest.raises(ParseError):
        ingest_raw_bytes(b"x", "bad.bin", "dev", "x", meta)

    store = LocalBlobStore(local_store)
    key = "dead_letter/dev/abc/error.json"
    assert store.exists(key)
    err = json.loads(store.get_bytes(key))
    assert err["stage"] == "parse"

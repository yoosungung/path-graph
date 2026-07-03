import json

import pytest

from path_graph.collectors.remote import collect_local_file
from path_graph.config import get_settings
from path_graph.ids import document_id
from path_graph.steps.ingest_helpers import parse_manifest_line
from path_graph.steps.ingest_manifest import main as ingest_manifest_main
from constants import PROJECT_ID


def test_parse_manifest_line_adds_document_id():
    raw = {
        "tenant": "dev",
        "project_id": PROJECT_ID,
        "source_id": "sharepoint:kms",
        "content_hash": "abc123",
        "s3_raw_uri": "s3://path-graph/raw/dev/x/abc123/doc.pdf",
        "filename": "doc.pdf",
    }
    meta = parse_manifest_line(raw)
    assert meta["document_id"] == document_id("dev", PROJECT_ID, "abc123")
    assert meta["filename"] == "doc.pdf"


def test_parse_manifest_line_from_json_string():
    raw = json.dumps(
        {
            "tenant": "dev",
            "project_id": PROJECT_ID,
            "source_id": "web",
            "content_hash": "deadbeef",
            "s3_raw_uri": "file://x",
            "filename": "a.txt",
        }
    )
    meta = parse_manifest_line(raw, tenant="dev")
    assert meta["tenant"] == "dev"


def test_ingest_manifest_cli(local_store, monkeypatch):
    monkeypatch.setattr(
        "path_graph.parsers.parse.parse_document",
        lambda data, filename, rhwp_bin="rhwp-batch": ("# Hi\n\nBody", None),
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest_manifest.resolve_project_slug",
        lambda *a, **k: "default",
    )
    f = local_store / "note.txt"
    f.write_text("hello", encoding="utf-8")
    meta = collect_local_file(f, "dev", PROJECT_ID, "local")
    line = json.dumps(
        {
            "tenant": meta["tenant"],
            "project_id": PROJECT_ID,
            "source_id": meta["source_id"],
            "content_hash": meta["content_hash"],
            "s3_raw_uri": meta["s3_raw_uri"],
            "filename": meta["filename"],
            "document_id": meta["document_id"],
        }
    )
    rc = ingest_manifest_main(["--tenant", "dev", "--manifest-line", line])
    assert rc == 0


def test_ingest_manifest_reads_manifest_line_env(local_store, monkeypatch):
    monkeypatch.setattr(
        "path_graph.parsers.parse.parse_document",
        lambda data, filename, rhwp_bin="rhwp-batch": ("text", None),
    )
    monkeypatch.setattr(
        "path_graph.steps.ingest_manifest.resolve_project_slug",
        lambda *a, **k: "default",
    )
    f = local_store / "env.txt"
    f.write_text("x", encoding="utf-8")
    meta = collect_local_file(f, "dev", PROJECT_ID, "local")
    monkeypatch.setenv(
        "MANIFEST_LINE",
        json.dumps(
            {
                "tenant": meta["tenant"],
                "project_id": PROJECT_ID,
                "source_id": meta["source_id"],
                "content_hash": meta["content_hash"],
                "s3_raw_uri": meta["s3_raw_uri"],
                "filename": meta["filename"],
                "document_id": meta["document_id"],
            }
        ),
    )
    rc = ingest_manifest_main(["--tenant", "dev"])
    assert rc == 0


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PIPELINE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("PATH_GRAPH_DSN", "")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()

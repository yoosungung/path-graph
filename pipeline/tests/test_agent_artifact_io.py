"""Artifact fetch helpers shared by graph-extractor / wiki-synthesizer bundles."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_SRC = REPO_ROOT / "agents" / "graph-extractor" / "src"
WIKI_SRC = REPO_ROOT / "agents" / "wiki-synthesizer" / "src"


@pytest.fixture(params=["graph_extractor", "wiki_synthesizer"])
def artifact_io_module(request):
    src = GRAPH_SRC if request.param == "graph_extractor" else WIKI_SRC
    sys.path.insert(0, str(src))
    try:
        yield importlib.import_module(f"{request.param}.artifact_io")
    finally:
        sys.path.remove(str(src))


def test_fetch_bytes_reads_file_uri(artifact_io_module, tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"artifact-bytes")
    assert artifact_io_module.fetch_bytes(path.as_uri()) == b"artifact-bytes"


def test_fetch_bytes_rejects_unsupported_scheme(artifact_io_module):
    with pytest.raises(ValueError, match="unsupported artifact uri scheme"):
        artifact_io_module.fetch_bytes("s3://bucket/key")


def test_graph_read_jsonl_bytes(artifact_io_module):
    if not hasattr(artifact_io_module, "read_jsonl_bytes"):
        pytest.skip("read_jsonl_bytes is graph-extractor only")
    raw = (
        json.dumps({"chunk_id": "c1", "text": "Alpha"}) + "\n"
        + json.dumps({"chunk_id": "c2", "text": "Beta"}) + "\n"
    ).encode()
    lines = artifact_io_module.read_jsonl_bytes(raw)
    assert len(lines) == 2
    assert lines[0]["text"] == "Alpha"


def test_wiki_read_json_bytes(artifact_io_module):
    if not hasattr(artifact_io_module, "read_json_bytes"):
        pytest.skip("read_json_bytes is wiki-synthesizer only")
    obj = artifact_io_module.read_json_bytes(
        json.dumps({"entities": [], "edges": []}).encode()
    )
    assert obj == {"entities": [], "edges": []}

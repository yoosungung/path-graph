from __future__ import annotations

import json

import pytest

from path_graph.collectors.remote import collect_local_file, write_batch_manifest
from path_graph.config import get_settings
from path_graph.contracts.s3_keys import s3_key_batch_manifest
from path_graph.steps.load_batch_manifest import main as load_main, resolve_manifest_json


from constants import PROJECT_ID


def test_resolve_manifest_json_from_key(local_store):
    local_store.mkdir(parents=True, exist_ok=True)
    f = local_store / "doc.txt"
    f.write_text("hello", encoding="utf-8")
    meta = collect_local_file(f, "dev", PROJECT_ID, "local")
    write_batch_manifest("dev", "batch-load", [meta], get_settings())
    manifest_key = s3_key_batch_manifest("dev", "batch-load")
    payload = resolve_manifest_json(manifest_key=manifest_key)
    rows = json.loads(payload)
    assert len(rows) == 1
    assert rows[0]["tenant"] == "dev"
    assert rows[0]["project_id"] == PROJECT_ID
    assert rows[0]["filename"] == "doc.txt"


def test_resolve_manifest_json_inline():
    inline = json.dumps(
        [{"tenant": "dev", "project_id": PROJECT_ID, "source_id": "x", "content_hash": "a", "s3_raw_uri": "u", "filename": "f"}]
    )
    assert json.loads(resolve_manifest_json(batch_manifest=inline)) == json.loads(inline)


def test_resolve_manifest_json_requires_one_source():
    with pytest.raises(ValueError, match="batch_manifest_key or batch_manifest"):
        resolve_manifest_json()


def test_resolve_manifest_json_key_wins_over_inline(local_store):
    local_store.mkdir(parents=True, exist_ok=True)
    f = local_store / "doc.txt"
    f.write_text("hello", encoding="utf-8")
    meta = collect_local_file(f, "dev", PROJECT_ID, "local")
    write_batch_manifest("dev", "batch-priority", [meta], get_settings())
    manifest_key = s3_key_batch_manifest("dev", "batch-priority")
    broken_inline = json.dumps(
        [
            {
                "tenant": "dev",
                "source_id": "x",
                "content_hash": "a",
                "s3_raw_uri": "u",
                "filename": "wrong.pdf",
            }
        ]
    )
    rows = json.loads(
        resolve_manifest_json(manifest_key=manifest_key, batch_manifest=broken_inline)
    )
    assert len(rows) == 1
    assert rows[0]["project_id"] == PROJECT_ID
    assert rows[0]["filename"] == "doc.txt"


def test_resolve_manifest_json_inline_requires_project_id():
    inline = json.dumps(
        [
            {
                "tenant": "dev",
                "source_id": "x",
                "content_hash": "a",
                "s3_raw_uri": "u",
                "filename": "f",
            }
        ]
    )
    with pytest.raises(Exception):
        resolve_manifest_json(batch_manifest=inline)


def test_load_batch_manifest_cli_writes_output(tmp_path, local_store):
    local_store.mkdir(parents=True, exist_ok=True)
    f = local_store / "doc.txt"
    f.write_text("hello", encoding="utf-8")
    meta = collect_local_file(f, "dev", PROJECT_ID, "local")
    write_batch_manifest("dev", "batch-cli", [meta], get_settings())
    out = tmp_path / "manifest.json"
    rc = load_main(
        [
            "--tenant",
            "dev",
            "--manifest-key",
            s3_key_batch_manifest("dev", "batch-cli"),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    rows = json.loads(out.read_text())
    assert len(rows) == 1
    assert rows[0]["project_id"] == PROJECT_ID

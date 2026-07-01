from __future__ import annotations

import json

from path_graph.collectors.remote import collect_local_file, write_batch_manifest
from path_graph.config import get_settings
from path_graph.contracts.s3_keys import s3_key_batch_manifest, s3_key_batch_meta
from path_graph.steps.load_batch_manifest import resolve_max_parallel

from constants import PROJECT_ID


def test_write_batch_manifest_writes_meta(local_store):
    local_store.mkdir(parents=True, exist_ok=True)
    f = local_store / "doc.txt"
    f.write_text("hello", encoding="utf-8")
    meta = collect_local_file(f, "dev", PROJECT_ID, "local")
    write_batch_manifest("dev", "batch-meta", [meta], get_settings(), max_parallel=3)
    store = __import__("path_graph.storage.blob", fromlist=["make_blob_store"]).make_blob_store(
        get_settings()
    )
    raw = store.get_bytes(s3_key_batch_meta("dev", "batch-meta"))
    payload = json.loads(raw.decode("utf-8"))
    assert payload["max_parallel"] == 3


def test_resolve_max_parallel_from_meta(local_store):
    local_store.mkdir(parents=True, exist_ok=True)
    f = local_store / "doc.txt"
    f.write_text("hello", encoding="utf-8")
    item = collect_local_file(f, "dev", PROJECT_ID, "local")
    write_batch_manifest("dev", "batch-mp", [item], get_settings(), max_parallel=4)
    manifest_key = s3_key_batch_manifest("dev", "batch-mp")
    assert resolve_max_parallel(manifest_key=manifest_key) == 4


def test_resolve_max_parallel_default_when_meta_missing():
    assert resolve_max_parallel(manifest_key="") == 10
    assert resolve_max_parallel(manifest_key="batches/dev/x/manifest.jsonl", fallback=7) == 7

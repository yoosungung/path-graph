from __future__ import annotations

import json
from typing import Any

from path_graph.chunkers.chunk import chunk_from_markdown, chunk_from_rhwp_json, chunks_to_jsonl_lines
from path_graph.config import get_settings
from path_graph.contracts.s3_keys import (
    s3_key_chunks,
    s3_key_dead_letter,
    s3_key_parsed_json,
    s3_key_parsed_md,
    s3_key_parsed_meta,
)
from path_graph.parsers.parse import parse_document
from path_graph.storage.blob import make_blob_store, write_jsonl


class ParseError(Exception):
    pass


def ingest_raw_bytes(
    data: bytes,
    filename: str,
    tenant: str,
    source_id: str,
    meta: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    store = make_blob_store(settings)
    doc_id = meta["document_id"]
    content_hash = meta["content_hash"]

    try:
        parsed_text, rhwp_doc = parse_document(
            data, filename, rhwp_bin=settings.rhwp_batch_bin
        )
    except Exception as exc:
        dl_key = s3_key_dead_letter(tenant, content_hash)
        store.put_bytes(
            dl_key,
            json.dumps({"stage": "parse", "error": str(exc)}).encode("utf-8"),
        )
        raise ParseError(str(exc)) from exc

    if rhwp_doc is not None:
        parsed_key = s3_key_parsed_json(tenant, doc_id)
        store.put_bytes(parsed_key, parsed_text.encode("utf-8"))
        chunks = chunk_from_rhwp_json(
            rhwp_doc,
            tenant,
            content_hash,
            meta["project_id"],
            max_chars=settings.chunk_max_chars,
        )
    else:
        parsed_key = s3_key_parsed_md(tenant, doc_id)
        store.put_bytes(parsed_key, parsed_text.encode("utf-8"))
        chunks = chunk_from_markdown(
            parsed_text,
            tenant,
            content_hash,
            meta["project_id"],
            max_chars=settings.chunk_max_chars,
        )

    meta_key = s3_key_parsed_meta(tenant, doc_id)
    store.put_bytes(
        meta_key,
        json.dumps(
            {
                **meta,
                "parsed_key": parsed_key,
                "chunk_count": len(chunks),
            },
            ensure_ascii=False,
        ).encode("utf-8"),
    )

    chunks_key = s3_key_chunks(tenant, doc_id)
    chunks_uri = write_jsonl(chunks_key, chunks_to_jsonl_lines(chunks), store)

    return {
        **meta,
        "parsed_uri": store.uri_for(parsed_key),
        "chunks_uri": chunks_uri,
        "chunks_key": chunks_key,
        "chunks": chunks,
    }

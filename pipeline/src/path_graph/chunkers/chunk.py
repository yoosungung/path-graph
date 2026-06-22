from __future__ import annotations

import json
from typing import Any

from path_graph.contracts.schemas import ChunkRecord
from path_graph.ids import chunk_id, document_id, sha256_text


def chunk_from_markdown(
    text: str,
    tenant: str,
    content_hash: str,
    *,
    max_chars: int = 1500,
) -> list[ChunkRecord]:
    doc_id = document_id(tenant, content_hash)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text] if text.strip() else []
    chunks: list[ChunkRecord] = []
    buf: list[str] = []
    size = 0
    idx = 0

    def flush() -> None:
        nonlocal idx, buf, size
        if not buf:
            return
        body = "\n\n".join(buf)
        th = sha256_text(body)
        chunks.append(
            ChunkRecord(
                chunk_id=chunk_id(tenant, doc_id, idx, th),
                document_id=doc_id,
                tenant=tenant,
                chunk_index=idx,
                text=body,
                text_hash=th,
                heading_path=[],
                source_block_type="paragraph",
            )
        )
        idx += 1
        buf = []
        size = 0

    for para in paragraphs:
        if size + len(para) > max_chars and buf:
            flush()
        buf.append(para)
        size += len(para)
    flush()
    return chunks


def chunk_from_rhwp_json(doc: dict[str, Any], tenant: str, content_hash: str) -> list[ChunkRecord]:
    doc_id = document_id(tenant, content_hash)
    blocks = doc.get("blocks") or []
    chunks: list[ChunkRecord] = []
    idx = 0
    for block in blocks:
        btype = block.get("type", "paragraph")
        text = block.get("text") or block.get("markdown") or ""
        if btype == "table" and not text:
            text = json.dumps(block.get("rows") or [], ensure_ascii=False)
        if not str(text).strip():
            continue
        body = str(text)
        th = sha256_text(body)
        chunks.append(
            ChunkRecord(
                chunk_id=chunk_id(tenant, doc_id, idx, th),
                document_id=doc_id,
                tenant=tenant,
                chunk_index=idx,
                text=body,
                text_hash=th,
                heading_path=list(block.get("heading_path") or []),
                source_block_type=btype,
            )
        )
        idx += 1
    return chunks


def chunks_to_jsonl_lines(chunks: list[ChunkRecord]) -> list[dict]:
    return [c.model_dump() for c in chunks]

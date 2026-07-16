"""Chunk directly from PyMuPDF4LLM ``to_json()`` documents."""

from __future__ import annotations

from typing import Any, Mapping

from path_graph.chunkers.chunk import _split_oversized
from path_graph.contracts.schemas import ChunkRecord
from path_graph.ids import chunk_id, document_id, sha256_text
from path_graph.parsers.pymupdf_json import (
    box_chunk_role,
    box_text,
    iter_layout_boxes,
    table_markdown,
)


def chunk_from_pymupdf_json(
    doc: Mapping[str, Any],
    tenant: str,
    content_hash: str,
    project_id: str,
    *,
    max_chars: int = 1000,
) -> list[ChunkRecord]:
    doc_id = document_id(tenant, project_id, content_hash)
    chunks: list[ChunkRecord] = []
    heading_stack: list[str] = []
    idx = 0
    pending_caption: str | None = None

    for _page_num, box in iter_layout_boxes(doc):
        boxclass = str(box.get("boxclass") or "text").lower()
        text = box_text(box)
        role = box_chunk_role(boxclass, text)
        if role is None:
            continue

        if role == "caption":
            pending_caption = text
            continue

        if role == "heading":
            if text:
                heading_stack = [text]
            continue

        if role == "image":
            caption = str(box.get("caption") or pending_caption or "").strip()
            pending_caption = None
            if not caption:
                continue
            th = sha256_text(caption)
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id(tenant, doc_id, idx, th),
                    document_id=doc_id,
                    tenant=tenant,
                    project_id=project_id,
                    chunk_index=idx,
                    text=caption,
                    text_hash=th,
                    heading_path=list(heading_stack),
                    source_block_type="image",
                )
            )
            idx += 1
            continue

        pending_caption = None
        if role == "table":
            body = table_markdown(box)
            block_type = "table"
        else:
            body = text
            block_type = role

        if not body:
            continue

        for piece in _split_oversized(body, max_chars):
            th = sha256_text(piece)
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id(tenant, doc_id, idx, th),
                    document_id=doc_id,
                    tenant=tenant,
                    project_id=project_id,
                    chunk_index=idx,
                    text=piece,
                    text_hash=th,
                    heading_path=list(heading_stack),
                    source_block_type=block_type,
                )
            )
            idx += 1

    return chunks

from __future__ import annotations

import json
from typing import Any

from path_graph.contracts.schemas import ChunkRecord
from path_graph.ids import chunk_id, document_id, sha256_text


def _split_oversized(text: str, max_chars: int) -> list[str]:
    """Hard-split text longer than max_chars (prefer line/word boundaries)."""
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_chars:
            parts.append(rest.strip())
            break
        window = rest[:max_chars]
        cut = window.rfind("\n")
        if cut < max_chars // 3:
            cut = window.rfind(" ")
        if cut < max_chars // 3:
            cut = max_chars
        piece = rest[:cut].strip()
        if piece:
            parts.append(piece)
        rest = rest[cut:].lstrip()
    return [p for p in parts if p]


def chunk_from_markdown(
    text: str,
    tenant: str,
    content_hash: str,
    project_id: str,
    *,
    max_chars: int = 1000,
) -> list[ChunkRecord]:
    doc_id = document_id(tenant, project_id, content_hash)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    expanded: list[str] = []
    for para in paragraphs:
        if len(para) > max_chars:
            expanded.extend(_split_oversized(para, max_chars))
        else:
            expanded.append(para)

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
                project_id=project_id,
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

    for piece in expanded:
        piece_len = len(piece)
        if piece_len > max_chars:
            if buf:
                flush()
            for sub in _split_oversized(piece, max_chars):
                chunks.append(
                    ChunkRecord(
                        chunk_id=chunk_id(tenant, doc_id, idx, sha256_text(sub)),
                        document_id=doc_id,
                        tenant=tenant,
                        project_id=project_id,
                        chunk_index=idx,
                        text=sub,
                        text_hash=sha256_text(sub),
                        heading_path=[],
                        source_block_type="paragraph",
                    )
                )
                idx += 1
            continue
        join_overhead = 2 if buf else 0
        if size + join_overhead + piece_len > max_chars and buf:
            flush()
        buf.append(piece)
        size += piece_len + (2 if len(buf) > 1 else 0)
    flush()
    return chunks


def _block_chunk_text(block: dict[str, Any], btype: str) -> str:
    """Pick chunk body by block type (DESIGN type-aware rules)."""
    if btype == "table":
        text = block.get("markdown") or block.get("text") or ""
        if not text:
            text = json.dumps(block.get("rows") or [], ensure_ascii=False)
        return str(text).strip()
    if btype == "image":
        return str(block.get("caption") or block.get("text") or "").strip()
    return str(block.get("text") or block.get("markdown") or "").strip()


def chunk_from_blocks(
    doc: dict[str, Any],
    tenant: str,
    content_hash: str,
    project_id: str,
    *,
    max_chars: int = 1000,
) -> list[ChunkRecord]:
    """Chunk from ``content.json`` blocks only.

    Type-aware rules (pipeline/DESIGN.md Blocks):
    - ``heading``: not emitted as chunks (path only on later blocks)
    - ``table``: prefer whole HTML/markdown as one chunk; hard-split only if oversized
    - ``image``: caption text; reading order preserved by block order
    - ``page``/``bbox`` stay on blocks — never copied onto ``ChunkRecord``
    """
    doc_id = document_id(tenant, project_id, content_hash)
    blocks = doc.get("blocks") or []
    chunks: list[ChunkRecord] = []
    idx = 0
    for block in blocks:
        btype = block.get("type", "paragraph")
        if btype == "heading":
            continue
        text = _block_chunk_text(block, btype)
        if not text:
            continue
        heading_path = list(block.get("heading_path") or [])
        for body in _split_oversized(text, max_chars):
            th = sha256_text(body)
            chunks.append(
                ChunkRecord(
                    chunk_id=chunk_id(tenant, doc_id, idx, th),
                    document_id=doc_id,
                    tenant=tenant,
                    project_id=project_id,
                    chunk_index=idx,
                    text=body,
                    text_hash=th,
                    heading_path=heading_path,
                    source_block_type=btype,
                )
            )
            idx += 1
    return chunks


def chunks_to_jsonl_lines(chunks: list[ChunkRecord]) -> list[dict]:
    return [c.model_dump() for c in chunks]

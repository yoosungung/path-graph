"""PyMuPDF4LLM page_chunks / layout boxes → content.json blocks (#293)."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from path_graph.parsers.blocks_contract import normalize_blocks_document

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")


def _as_bbox(raw: Any) -> list[float] | None:
    if isinstance(raw, Sequence) and len(raw) >= 4 and not isinstance(raw, (str, bytes)):
        return [float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])]
    return None


def _page_number(page: Mapping[str, Any]) -> int | None:
    meta = page.get("metadata")
    if isinstance(meta, Mapping) and meta.get("page_number") is not None:
        return int(meta["page_number"])
    return None


def _slice_text(text: str, pos: Any) -> str:
    if not isinstance(pos, Sequence) or len(pos) < 2:
        return ""
    start, stop = int(pos[0]), int(pos[1])
    return text[start:stop]


def _blocks_from_markdown_slice(slice_text: str, *, page: int | None, bbox: list[float] | None) -> list[dict]:
    """Minimal markdown → blocks for a page_box text slice (headings / paragraphs)."""
    blocks: list[dict[str, Any]] = []
    heading_stack: list[str] = []
    paragraphs: list[str] = []

    def flush_para() -> None:
        nonlocal paragraphs
        body = "\n".join(paragraphs).strip()
        paragraphs = []
        if not body:
            return
        block: dict[str, Any] = {
            "type": "paragraph",
            "text": body,
            "heading_path": list(heading_stack),
        }
        metadata: dict[str, Any] = {}
        if page is not None:
            metadata["page"] = page
        if bbox is not None:
            metadata["bbox"] = bbox
        if metadata:
            block["metadata"] = metadata
        blocks.append(block)

    for line in slice_text.splitlines():
        m = _HEADING_RE.match(line.strip())
        if m:
            flush_para()
            level = len(m.group(1))
            title = m.group(2).strip()
            while len(heading_stack) >= level:
                heading_stack.pop()
            heading_stack.append(title)
            block = {
                "type": "heading",
                "text": title,
                "heading_path": list(heading_stack),
            }
            metadata = {}
            if page is not None:
                metadata["page"] = page
            if bbox is not None:
                metadata["bbox"] = bbox
            if metadata:
                block["metadata"] = metadata
            blocks.append(block)
            continue
        if line.strip():
            paragraphs.append(line.rstrip())
        else:
            flush_para()
    flush_para()
    return blocks


def _is_image_markdown(text: str) -> bool:
    s = text.strip()
    return s.startswith("![") or s.startswith("<img")


def blocks_from_pymupdf_page_chunks(pages: Sequence[Mapping[str, Any]]) -> dict:
    """Convert PyMuPDF4LLM ``page_chunks=True`` output to blocks document.

    Prefer ``page_boxes`` reading order when present; fall back to markdown
    heuristics on ``text`` only if boxes are absent.
    """
    blocks: list[dict[str, Any]] = []
    heading_stack: list[str] = []

    for page in pages:
        page_no = _page_number(page)
        text = str(page.get("text") or "")
        page_boxes = page.get("page_boxes")
        if not isinstance(page_boxes, Sequence) or not page_boxes:
            # No layout boxes — treat whole page markdown as text slices.
            for block in _blocks_from_markdown_slice(text, page=page_no, bbox=None):
                if block["type"] == "heading":
                    heading_stack = list(block["heading_path"])
                blocks.append(block)
            continue

        ordered = sorted(
            [b for b in page_boxes if isinstance(b, Mapping)],
            key=lambda b: int(b.get("index", 0)),
        )
        i = 0
        while i < len(ordered):
            box = ordered[i]
            cls = str(box.get("class") or "text").lower()
            bbox = _as_bbox(box.get("bbox"))
            slice_text = _slice_text(text, box.get("pos")).strip()
            metadata: dict[str, Any] = {}
            if page_no is not None:
                metadata["page"] = page_no
            if bbox is not None:
                metadata["bbox"] = bbox

            if cls in {"table"}:
                if not slice_text:
                    i += 1
                    continue
                block = {
                    "type": "table",
                    "markdown": slice_text,
                    "heading_path": list(heading_stack),
                }
                if metadata:
                    block["metadata"] = metadata
                blocks.append(block)
                i += 1
                continue

            if cls in {"picture", "image"}:
                caption = ""
                # Merge following text box as caption when adjacent.
                if i + 1 < len(ordered):
                    nxt = ordered[i + 1]
                    nxt_cls = str(nxt.get("class") or "").lower()
                    nxt_text = _slice_text(text, nxt.get("pos")).strip()
                    if nxt_cls == "text" and nxt_text and not _HEADING_RE.match(nxt_text.splitlines()[0]):
                        caption = nxt_text
                        i += 1
                if not caption and _is_image_markdown(slice_text):
                    caption = ""
                block = {
                    "type": "image",
                    "caption": caption,
                    "heading_path": list(heading_stack),
                }
                if metadata:
                    block["metadata"] = metadata
                blocks.append(block)
                i += 1
                continue

            # text / other → heading or paragraph slices
            for block in _blocks_from_markdown_slice(slice_text, page=page_no, bbox=bbox):
                if block["type"] == "heading":
                    heading_stack = list(block["heading_path"])
                else:
                    block["heading_path"] = list(heading_stack)
                blocks.append(block)
            i += 1

    return normalize_blocks_document({"blocks": blocks}, extractor="pymupdf4llm")

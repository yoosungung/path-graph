"""PyMuPDF4LLM ``to_json()`` document helpers (read-only; no blocks conversion)."""

from __future__ import annotations

import re
from typing import Any, Iterator, Mapping, Sequence

_HEADING_BOXCLASSES = frozenset({"title", "section-header"})
_SKIP_BOXCLASSES = frozenset({"page-header", "page-footer"})
_NUMBERED_HEADING_RE = re.compile(r"^\d+\.\s+\S")
_PAGE_NUMBER_LINE_RE = re.compile(r"^-\s*\d+\s*-$")


def is_pymupdf_json_document(doc: Mapping[str, Any]) -> bool:
    return isinstance(doc.get("pages"), list) and "page_count" in doc


def box_bbox(box: Mapping[str, Any]) -> list[float] | None:
    try:
        return [
            float(box["x0"]),
            float(box["y0"]),
            float(box["x1"]),
            float(box["y1"]),
        ]
    except (KeyError, TypeError, ValueError):
        return None


def box_text(box: Mapping[str, Any]) -> str:
    parts: list[str] = []
    textlines = box.get("textlines")
    if not isinstance(textlines, Sequence):
        return ""
    for line in textlines:
        if not isinstance(line, Mapping):
            continue
        spans = line.get("spans")
        if not isinstance(spans, Sequence):
            continue
        line_parts = [str(span.get("text") or "") for span in spans if isinstance(span, Mapping)]
        body = "".join(line_parts).strip()
        if body:
            parts.append(body)
    return "\n".join(parts).strip()


def table_markdown(box: Mapping[str, Any]) -> str:
    table = box.get("table")
    if isinstance(table, Mapping):
        markdown = str(table.get("markdown") or "").strip()
        if markdown:
            return markdown
    return box_text(box)


def is_numbered_heading(text: str) -> bool:
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    return bool(_NUMBERED_HEADING_RE.match(first))


def is_page_number_line(text: str) -> bool:
    return bool(_PAGE_NUMBER_LINE_RE.match(text.strip()))


def box_chunk_role(boxclass: str, text: str) -> str | None:
    """Return chunk role for a box: heading, paragraph, table, image, list_item, skip."""
    if boxclass in _SKIP_BOXCLASSES:
        return None
    if boxclass == "table":
        return "table"
    if boxclass in {"picture", "image"}:
        return "image"
    if boxclass in _HEADING_BOXCLASSES:
        return "heading"
    if boxclass == "list-item":
        return "list_item"
    if boxclass == "caption":
        return "caption"
    if boxclass == "text" and is_numbered_heading(text):
        return "heading"
    if is_page_number_line(text):
        return None
    if text.strip():
        return "paragraph"
    return None


def iter_layout_boxes(doc: Mapping[str, Any]) -> Iterator[tuple[int | None, Mapping[str, Any]]]:
    pages = doc.get("pages")
    if not isinstance(pages, Sequence):
        return
    for page in pages:
        if not isinstance(page, Mapping):
            continue
        page_no = page.get("page_number")
        page_num = int(page_no) if page_no is not None else None
        boxes = page.get("boxes")
        if not isinstance(boxes, Sequence):
            continue
        for box in boxes:
            if isinstance(box, Mapping):
                yield page_num, box
